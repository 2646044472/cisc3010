import json
import tempfile
import unittest
from pathlib import Path

from kafka_demo import storage
from kafka_demo.runner import Config, make_events


class CorrectnessTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / "audit.sqlite3"
        storage.initialize(self.path)
        self.db = storage.connect(self.path)
        self.events = make_events(8, 3010, "test")
        with self.db:
            self.db.executemany("INSERT INTO expected(event_id,payload,partition_id,delivered) VALUES(?,?,?,1)",
                                [(e["event_id"], json.dumps(e), e["sequence"] % 4) for e in self.events])

    def tearDown(self):
        self.db.close()
        self.temp.cleanup()

    def apply_all(self, idempotent=False):
        for i, event in enumerate(self.events):
            attempt = storage.begin_attempt(self.db, event["event_id"], "c1", i % 4, i // 4)
            storage.apply_effect(self.db, event, "c1", attempt, idempotent)
            storage.mark_committed(self.db, attempt)

    def test_correct_result_and_mutation_detection(self):
        self.apply_all()
        self.assertTrue(storage.check(self.db)["data_correct"])
        with self.db:
            self.db.execute("UPDATE effects SET usage_units=0 WHERE id=1")
        report = storage.check(self.db)
        self.assertFalse(report["data_correct"])
        self.assertEqual(report["invalid_effect_rows"], [1])

    def test_non_idempotent_replay_changes_business_total(self):
        self.apply_all()
        event = self.events[0]
        attempt = storage.begin_attempt(self.db, event["event_id"], "c2", 0, 0)
        storage.apply_effect(self.db, event, "c2", attempt, False)
        report = storage.check(self.db)
        self.assertEqual(report["duplicate_effects"], {event["event_id"]: 2})
        self.assertGreater(report["actual_usage_units"], report["expected_usage_units"])
        self.assertTrue(storage.verify_scenario(report, "replay", 1))

    def test_idempotence_preserves_replay_evidence(self):
        self.apply_all(True)
        event = self.events[0]
        attempt = storage.begin_attempt(self.db, event["event_id"], "c2", 0, 0)
        self.assertFalse(storage.apply_effect(self.db, event, "c2", attempt, True))
        report = storage.check(self.db)
        self.assertTrue(report["data_correct"])
        self.assertEqual(report["replayed_ids"], {event["event_id"]: 2})
        self.assertTrue(storage.verify_scenario(report, "idempotent", 1))

    def test_dedup_marker_rolls_back_with_failed_effect(self):
        # A marker must never survive if the associated business write fails.
        with self.db:
            self.db.execute("CREATE TRIGGER reject_effect BEFORE INSERT ON effects BEGIN SELECT RAISE(ABORT,'injected'); END")
        event = self.events[0]
        attempt = storage.begin_attempt(self.db, event["event_id"], "c1", 0, 0)
        with self.assertRaises(Exception):
            storage.apply_effect(self.db, event, "c1", attempt, True)
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM dedup_keys").fetchone()[0], 0)
        with self.db:
            self.db.execute("DROP TRIGGER reject_effect")
        self.assertTrue(storage.apply_effect(self.db, event, "c1", attempt, True))

    def test_missing_unexpected_and_unpublished_are_detected(self):
        self.apply_all()
        with self.db:
            self.db.execute("DELETE FROM effects WHERE event_id=?", (self.events[0]["event_id"],))
            self.db.execute("INSERT INTO effects(event_id,consumer_id,usage_units,created_at) VALUES('alien','c2',10,0)")
            self.db.execute("UPDATE expected SET delivered=0 WHERE event_id=?", (self.events[1]["event_id"],))
        report = storage.check(self.db)
        self.assertEqual(report["missing_ids"], [self.events[0]["event_id"]])
        self.assertEqual(report["unexpected_ids"], ["alien"])
        self.assertFalse(storage.verify_scenario(report, "loss", 1))

    def test_config_rejects_invalid_input_and_dataset_repeats(self):
        with self.assertRaises(ValueError):
            Config(consumers=0).validate()
        with self.assertRaises(ValueError):
            Config(events=True).validate()
        a, b = make_events(8, 3010, "a"), make_events(8, 3010, "b")
        self.assertEqual([{k:v for k,v in e.items() if k!='event_id'} for e in a],
                         [{k:v for k,v in e.items() if k!='event_id'} for e in b])


if __name__ == "__main__":
    unittest.main()
