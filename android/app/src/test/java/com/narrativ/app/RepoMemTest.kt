package com.narrativ.app

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test

/** Repo's in-memory copy of published files (load latency fix): what may replace what, and the size bound. */
class RepoMemTest {
    @Before fun clear() = Repo.memClear()

    @Test fun phoneCopyNeverReplacesNetworkCopy() {
        Repo.memPut("data/a.json", "new", net = true, etag = "\"n\"")
        Repo.memPut("data/a.json", "old", net = false, etag = "\"o\"")
        assertEquals("new", Repo.memText("data/a.json"))
        assertEquals("new", Repo.memText("data/a.json", "\"n\""))
        assertNull(Repo.memText("data/a.json", "\"o\""))
        assertTrue(Repo.checkedRecently("data/a.json"))
    }

    @Test fun phoneCopyIsNotANetworkCheck() {
        Repo.memPut("data/b.json", "text", net = false)
        assertEquals("text", Repo.memText("data/b.json"))
        assertFalse(Repo.checkedRecently("data/b.json"))
        Repo.memPut("data/b.json", "text", net = true, etag = "\"t\"")  // a 304: same text, now confirmed
        assertTrue(Repo.checkedRecently("data/b.json"))
        assertEquals("text", Repo.memText("data/b.json", "\"t\""))
    }

    @Test fun decodedCopyOnlyBesideTheSameText() {
        Repo.memPut("data/c.json", "v1", net = true)
        Repo.memoPut("data/c.json", "K", "v1", 1)
        assertEquals(1, Repo.memoGet("data/c.json", "K", "v1"))
        assertEquals(1, Repo.memoPeek("data/c.json", "K"))
        assertNull(Repo.memoGet("data/c.json", "other type", "v1"))
        Repo.memoPut("data/c.json", "K", "v0", 0)  // an older text decoded late never replaces the newer one
        assertEquals(1, Repo.memoPeek("data/c.json", "K"))
        Repo.memPut("data/c.json", "v2", net = true)  // new text: decoded copies of the old one are dropped
        assertNull(Repo.memoGet("data/c.json", "K", "v1"))
        assertNull(Repo.memoPeek("data/c.json", "K"))
    }

    @Test fun preloadNeverDropsWhatIsHeld() {
        val big = "x".repeat((Repo.MEM_BUDGET / 3).toInt() + 1)
        Repo.memPut("p1", big + "1", net = true)
        Repo.memPut("p2", big + "2", net = true)
        Repo.memPutIfRoom("pre", big + "3", net = true)  // would push p1 out: not kept in memory
        assertNull(Repo.memText("pre"))
        assertNotNull(Repo.memText("p1"))
        assertNotNull(Repo.memText("p2"))
        Repo.memPutIfRoom("small", "s", net = true, etag = "\"s\"")  // fits: kept, and counts as a network check
        assertEquals("s", Repo.memText("small", "\"s\""))
        assertTrue(Repo.checkedRecently("small"))
        Repo.memPutIfRoom("p1", big + "1b", net = true)  // replacing a held file of the same size fits
        assertEquals(big + "1b", Repo.memText("p1"))
    }

    @Test fun budgetDropsLeastRecentlyUsed() {
        val big = "x".repeat((Repo.MEM_BUDGET / 3).toInt() + 1)
        Repo.memPut("p1", big + "1", net = false)
        Repo.memPut("p2", big + "2", net = false)
        assertNotNull(Repo.memText("p1"))  // p1 used, so p2 is the oldest
        Repo.memPut("p3", big + "3", net = false)
        assertNotNull(Repo.memText("p1"))
        assertNull(Repo.memText("p2"))
        assertNotNull(Repo.memText("p3"))
    }
}
