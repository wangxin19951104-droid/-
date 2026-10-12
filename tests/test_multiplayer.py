# -*- coding: utf-8 -*-
"""多人并行行为回归测试（不调用外部模型）。"""
import unittest
import time
from test_upgrade import h

class MultiplayerRegression(unittest.TestCase):
    def setUp(self):
        self.mod = h
        self.previous_holds = dict(h.HOLD)
        self.previous_works = dict(h.WORKS)
        h.HOLD.clear()
        h.WORKS.clear()

    def tearDown(self):
        h.HOLD.clear()
        h.HOLD.update(self.previous_holds)
        h.WORKS.clear()
        h.WORKS.update(self.previous_works)

    def test_different_clients_can_claim_different_projects(self):
        self.mod.claim("p1", "client-a")
        self.mod.claim("p2", "client-b")
        self.assertEqual(self.mod.HOLD["p1"]["client"], "client-a")
        self.assertEqual(self.mod.HOLD["p2"]["client"], "client-b")

    def test_same_project_is_exclusive(self):
        self.mod.claim("p1", "client-a")
        with self.assertRaises(RuntimeError):
            self.mod.claim("p1", "client-b")

    def test_owner_can_renew_and_release(self):
        self.mod.claim("p1", "client-a")
        self.mod.claim("p1", "client-a")
        self.mod.HOLD.pop("p1", None)
        self.mod.claim("p1", "client-b")
        self.assertEqual(self.mod.HOLD["p1"]["client"], "client-b")

    def test_expired_owner_can_be_replaced_but_running_job_cannot(self):
        self.mod.claim("p1", "client-a")
        self.mod.HOLD['p1']['seen'] = time.time() - h.HOLD_SECONDS - 1
        h.WORKS['p1'] = h.Work()
        h.WORKS['p1'].task['state'] = 'running'
        with self.assertRaises(RuntimeError):
            h.claim('p1', 'client-b')
        h.WORKS['p1'].task['state'] = 'idle'
        h.claim('p1', 'client-b')
        self.assertEqual(h.HOLD['p1']['client'], 'client-b')

if __name__ == "__main__":
    unittest.main()
