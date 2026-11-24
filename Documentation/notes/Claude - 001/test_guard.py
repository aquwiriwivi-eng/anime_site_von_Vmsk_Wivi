import asyncio, pytest
import shikimori_guard as g
from shikimori import ShikimoriError

class Clock:
    t = 1000.0
    def __call__(self): return self.t

@pytest.fixture(autouse=True)
def fresh(monkeypatch):
    clk = Clock(); monkeypatch.setattr(g, "now", clk)
    g._cache.clear(); g._inflight.clear(); g.gate = g.RateGate(); 
    calls = {"n": 0, "queries": []}
    async def fake(q):
        calls["n"] += 1; calls["queries"].append(q)
        await asyncio.sleep(0.01)
        return {"data": {"animes": [{"id": 1}]}}
    monkeypatch.setattr(g, "fetch_anime_from_shikimori", fake)
    return clk, calls

def run(c): return asyncio.run(c)

def test_gate_never_exceeds_5rps_90rpm_even_when_hammered(fresh):
    clk, _ = fresh
    allowed = []
    for _ in range(600):                 # 10 минут, 20 попыток в секунду (= «1000 посетителей»)
        for _ in range(20):
            if g.gate.try_acquire(): allowed.append(clk.t)
        clk.t += 1
    # проверяем ЛЮБОЕ окно
    assert max(sum(1 for a in allowed if s <= a < s + 1) for s in allowed) <= 5
    assert max(sum(1 for a in allowed if s <= a < s + 60) for s in allowed) <= 90
    print(f"\n  пропущено за 10 минут: {len(allowed)} (макс в минуту: {max(sum(1 for a in allowed if s <= a < s + 60) for s in allowed)})")

def test_1000_visitors_same_query_one_upstream_call(fresh):
    _, calls = fresh
    async def go():
        return await asyncio.gather(*(g.search_shikimori("Naruto") for _ in range(1000)))
    res = run(go())
    assert calls["n"] == 1 and len(res) == 1000

def test_query_normalization_and_cache(fresh):
    _, calls = fresh
    async def go():
        await g.search_shikimori("Naruto"); await g.search_shikimori("  naruto "); await g.search_shikimori("NARUTO")
    run(go()); assert calls["n"] == 1

def test_cache_expires(fresh):
    clk, calls = fresh
    async def go():
        await g.search_shikimori("a b"); clk.t += g.CACHE_TTL + 1; await g.search_shikimori("a b")
    run(go()); assert calls["n"] == 2

def test_300_distinct_queries_burst_is_capped_and_rest_get_busy(fresh):
    _, calls = fresh
    async def go():
        return await asyncio.gather(*(g.search_shikimori(f"title {i}") for i in range(300)), return_exceptions=True)
    res = run(go())
    busy = sum(isinstance(r, g.ShikimoriBusy) for r in res)
    assert calls["n"] == g.PER_SECOND and busy == 300 - g.PER_SECOND
    assert not any(isinstance(r, Exception) and not isinstance(r, g.ShikimoriBusy) for r in res)

def test_429_pauses_upstream(fresh, monkeypatch):
    clk, calls = fresh
    async def f429(q): calls["n"] += 1; raise ShikimoriError(429, "Retry later")
    monkeypatch.setattr(g, "fetch_anime_from_shikimori", f429)
    async def go():
        with pytest.raises(ShikimoriError): await g.search_shikimori("x1")
        for i in range(5):
            with pytest.raises(g.ShikimoriBusy): await g.search_shikimori(f"y{i}")
        clk.t += g.PAUSE_AFTER_429 + 1
        with pytest.raises(ShikimoriError): await g.search_shikimori("z")   # пауза кончилась, снова пробуем
    run(go()); assert calls["n"] == 2

def test_errors_not_cached(fresh, monkeypatch):
    clk, calls = fresh
    async def f500(q): calls["n"] += 1; raise ShikimoriError(500, "boom")
    monkeypatch.setattr(g, "fetch_anime_from_shikimori", f500)
    async def go():
        for _ in range(2):
            clk.t += 2
            with pytest.raises(ShikimoriError): await g.search_shikimori("same")
    run(go()); assert calls["n"] == 2

def test_empty_result_cached_shorter(fresh, monkeypatch):
    clk, calls = fresh
    async def empty(q): calls["n"] += 1; return {"data": {"animes": []}}
    monkeypatch.setattr(g, "fetch_anime_from_shikimori", empty)
    async def go():
        await g.search_shikimori("nothing"); await g.search_shikimori("nothing")      # из кэша
        clk.t += g.EMPTY_TTL + 1; await g.search_shikimori("nothing")                 # час прошёл
    run(go()); assert calls["n"] == 2

def test_cache_is_bounded(fresh, monkeypatch):
    clk, _ = fresh
    monkeypatch.setattr(g, "MAX_CACHE", 50)
    async def go():
        for i in range(200):
            clk.t += 2; await g.search_shikimori(f"q{i}")
    run(go()); assert len(g._cache) <= 50
