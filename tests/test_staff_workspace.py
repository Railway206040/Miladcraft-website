"""Smoke tests for staff recruitment and role migration; uses an isolated SQLite database."""
import os
import tempfile
import unittest

_test_dir = tempfile.TemporaryDirectory(prefix="miladcraft-test-")
os.environ["DATA_DIR"] = _test_dir.name
os.environ["DB_PATH"] = os.path.join(_test_dir.name, "test.db")
os.environ["BOOTSTRAP_OWNER_USERNAME"] = "test_owner"
os.environ["BOOTSTRAP_OWNER_PASSWORD"] = "Test-Owner-Password-2026!"
os.environ["COOKIE_SECURE"] = "false"
os.environ["MINECRAFT_WEBHOOK_TOKEN"] = "test-webhook-token"

import app as site


class StaffWorkspaceTests(unittest.TestCase):
    def setUp(self):
        site.app.config.update(TESTING=True, SECRET_KEY="unit-test-secret")
        self.client = site.app.test_client()
        site.init_db()
        # Ensure the new portal schema is applied after the legacy app schema.
        with self.client:
            self.client.get("/workspace/apply")
        with site.connect_db() as db:
            db.execute("DELETE FROM staff_applications")
            db.execute("DELETE FROM staff_activity")
            db.execute("DELETE FROM build_tasks")
            db.execute("DELETE FROM staff_messages")
            db.execute("DELETE FROM staff_conversations WHERE kind='private'")
            db.execute("DELETE FROM staff_presence")
            db.execute("DELETE FROM staff_conversation_members WHERE staff_id != (SELECT id FROM staff WHERE username='test_owner')")
            db.execute("DELETE FROM staff WHERE username != 'test_owner'")
            db.execute("DELETE FROM projects")
            db.execute("DELETE FROM warnings")

    def test_application_requires_review_before_account_exists(self):
        response = self.client.post("/workspace/apply", data={
            "username": "new_builder", "display_name": "New Builder", "email": "builder@example.test",
            "age": "17", "minecraft_username": "BuilderMC", "requested_role": "builder",
            "telegram": "", "discord": "", "daily_hours": "3", "country": "Test",
            "experience": "Built spawn areas", "motivation": "Contribute to the server",
        }, follow_redirects=True)
        self.assertEqual(response.status_code, 200)
        with site.connect_db() as db:
            self.assertIsNone(db.execute("SELECT id FROM staff WHERE username='new_builder'").fetchone())
            application = db.execute("SELECT id,status FROM staff_applications WHERE username='new_builder'").fetchone()
            self.assertIsNotNone(application)
            self.assertEqual(application["status"], "pending")

        login = self.client.post("/account/login", data={
            "username": "test_owner", "password": "Test-Owner-Password-2026!"
        }, follow_redirects=False)
        self.assertIn(login.status_code, (302, 303))
        reviewed = self.client.post(
            f"/workspace/applications/{application['id']}/review",
            data={"decision": "accept", "review_note": "Approved in smoke test"},
            follow_redirects=True,
        )
        self.assertEqual(reviewed.status_code, 200)
        with site.connect_db() as db:
            account = db.execute("SELECT role,password_hash FROM staff WHERE username='new_builder'").fetchone()
            self.assertIsNotNone(account)
            self.assertEqual(account["role"], "builder")
            self.assertTrue(account["password_hash"].startswith("scrypt:") or account["password_hash"].startswith("pbkdf2:"))
            status = db.execute("SELECT status FROM staff_applications WHERE id=?", (application["id"],)).fetchone()
            self.assertEqual(status["status"], "accepted")

    def test_private_message_creates_only_participant_conversation(self):
        with site.connect_db() as db:
            db.execute("INSERT INTO staff(username,password_hash,role) VALUES(?,?,?)",
                       ("target_builder", site.generate_password_hash("Target-Password-2026!"), "builder"))
        self.client.post("/account/login", data={
            "username": "test_owner", "password": "Test-Owner-Password-2026!"
        })
        response = self.client.post("/workspace/messages/private", data={
            "recipient": "target_builder", "body": "Private smoke-test message"
        }, follow_redirects=False)
        self.assertIn(response.status_code, (302, 303))
        with site.connect_db() as db:
            convo = db.execute("SELECT id FROM staff_conversations WHERE kind='private'").fetchone()
            self.assertIsNotNone(convo)
            members = db.execute("SELECT COUNT(*) FROM staff_conversation_members WHERE conversation_id=?", (convo["id"],)).fetchone()[0]
            message = db.execute("SELECT body FROM staff_messages WHERE conversation_id=?", (convo["id"],)).fetchone()
            self.assertEqual(members, 2)
            self.assertEqual(message["body"], "Private smoke-test message")

    def test_minecraft_webhook_requires_token_and_updates_presence(self):
        with site.connect_db() as db:
            db.execute("INSERT INTO staff(username,password_hash,role) VALUES(?,?,?)",
                       ("minecraft_builder", site.generate_password_hash("Builder-Password-2026!"), "builder"))
        bad = self.client.post("/workspace/api/minecraft-event", json={
            "username": "minecraft_builder", "event": "join"
        })
        self.assertEqual(bad.status_code, 401)
        joined = self.client.post("/workspace/api/minecraft-event",
            headers={"X-MiladCraft-Token": "test-webhook-token"},
            json={"username": "minecraft_builder", "event": "join"})
        self.assertEqual(joined.status_code, 200)
        with site.connect_db() as db:
            presence = db.execute("SELECT is_online FROM staff_presence WHERE username='minecraft_builder'").fetchone()
            self.assertEqual(presence["is_online"], 1)
        quit_response = self.client.post("/workspace/api/minecraft-event",
            headers={"X-MiladCraft-Token": "test-webhook-token"},
            json={"username": "minecraft_builder", "event": "quit"})
        self.assertEqual(quit_response.status_code, 200)
        with site.connect_db() as db:
            presence = db.execute("SELECT is_online,total_minutes FROM staff_presence WHERE username='minecraft_builder'").fetchone()
            self.assertEqual(presence["is_online"], 0)
            self.assertGreaterEqual(presence["total_minutes"], 0)
            events = db.execute("SELECT COUNT(*) FROM staff_activity WHERE username='minecraft_builder' AND event_type LIKE 'minecraft_%'").fetchone()[0]
            self.assertEqual(events, 2)

    def test_unsupported_application_role_is_rejected(self):
        response = self.client.post("/workspace/apply", data={
            "username": "new_owner", "display_name": "Bad Request", "age": "20",
            "minecraft_username": "BadMC", "requested_role": "owner",
        }, follow_redirects=True)
        self.assertEqual(response.status_code, 200)
        with site.connect_db() as db:
            self.assertIsNone(db.execute("SELECT id FROM staff_applications WHERE username='new_owner'").fetchone())


if __name__ == "__main__":
    unittest.main()
