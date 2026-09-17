import tempfile
import unittest

from sessions import SessionNotFound, SessionStore


class SessionStoreTests(unittest.TestCase):
    def test_create_defaults_and_list_ordering(self):
        with tempfile.TemporaryDirectory() as directory:
            store = SessionStore(directory)
            first = store.create()
            second = store.create("Standup notes")
            self.assertTrue(first["name"].startswith("Session "))
            self.assertEqual(second["name"], "Standup notes")
            self.assertEqual(first["text"], "")

            listed = store.list()
            self.assertEqual([s["id"] for s in listed], [second["id"], first["id"]])
            self.assertNotIn("text", listed[0])
            self.assertIn("preview", listed[0])

    def test_rename_updates_name_and_timestamp(self):
        with tempfile.TemporaryDirectory() as directory:
            store = SessionStore(directory)
            created = store.create("Old name")
            updated = store.rename(created["id"], "New name")
            self.assertEqual(updated["name"], "New name")
            self.assertGreaterEqual(updated["updated_at"], created["updated_at"])
            self.assertEqual(store.get(created["id"])["name"], "New name")

    def test_append_text_joins_segments_with_a_space(self):
        with tempfile.TemporaryDirectory() as directory:
            store = SessionStore(directory)
            created = store.create()
            store.append_text(created["id"], "Hello", "en")
            store.append_text(created["id"], "world", "en")
            self.assertEqual(store.get(created["id"])["text"], "Hello world")

    def test_append_text_skips_extra_space_after_existing_whitespace(self):
        with tempfile.TemporaryDirectory() as directory:
            store = SessionStore(directory)
            created = store.create()
            store.append_text(created["id"], "Hello ", "en")
            store.append_text(created["id"], "world", "en")
            self.assertEqual(store.get(created["id"])["text"], "Hello world")

    def test_append_text_ignores_empty_segment(self):
        with tempfile.TemporaryDirectory() as directory:
            store = SessionStore(directory)
            created = store.create()
            store.append_text(created["id"], "", "en")
            self.assertEqual(store.get(created["id"])["text"], "")

    def test_open_segment_writes_under_the_session_directory(self):
        with tempfile.TemporaryDirectory() as directory:
            store = SessionStore(directory)
            created = store.create()
            segment = store.open_segment(created["id"], "en")
            try:
                self.assertEqual(segment.path.parent.name, "segments")
                self.assertEqual(segment.path.parent.parent.name, created["id"])
            finally:
                segment.close("stopped")

    def test_unknown_session_raises_not_found(self):
        with tempfile.TemporaryDirectory() as directory:
            store = SessionStore(directory)
            with self.assertRaises(SessionNotFound):
                store.get("missing")
            with self.assertRaises(SessionNotFound):
                store.rename("missing", "x")
            with self.assertRaises(SessionNotFound):
                store.append_text("missing", "x", "en")
            with self.assertRaises(SessionNotFound):
                store.open_segment("missing", "en")

    def test_path_traversal_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            store = SessionStore(directory)
            with self.assertRaises(SessionNotFound):
                store.get("../escape")
            with self.assertRaises(SessionNotFound):
                store.get("nested/child")


if __name__ == "__main__":
    unittest.main()
