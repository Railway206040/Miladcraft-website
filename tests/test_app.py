import os
import tempfile
import unittest

_TEST_DIR = tempfile.TemporaryDirectory(prefix="miladcraft-site-v2-")
os.environ["DATA_DIR"] = _TEST_DIR.name
os.environ["DB_PATH"] = os.path.join(_TEST_DIR.name, "test.db")
os.environ["BOOTSTRAP_OWNER_USERNAME"] = "test_owner"
os.environ["BOOTSTRAP_OWNER_PASSWORD"] = "Strong-Test-Owner-Password-2026!"
os.environ["COOKIE_SECURE"] = "false"
os.environ["MINECRAFT_WEBHOOK_TOKEN"] = "test-minecraft-token"

import app as site


class MiladCraftWebsiteTests(unittest.TestCase):
    def setUp(self):
        site.app.config.update(TESTING=True, SECRET_KEY="unit-test-secret")
        self.client = site.app.test_client()
        site.init_db()
        with site.connect_db() as db:
            for table in ("messages", "conversation_members", "conversations", "notifications",
                          "tasks", "project_members", "projects", "warnings", "staff_activity",
                          "staff_presence", "post_feedback", "post_comments", "post_tags",
                          "academy_tags", "posts", "news", "accounts"):
                db.execute(f"DELETE FROM {table}")
            owner_id = db.execute(
                "INSERT INTO accounts(username,password_hash,role,display_name) VALUES(?,?,?,?)",
                ("test_owner", site.generate_password_hash("Strong-Test-Owner-Password-2026!"), "owner", "Test Owner"),
            ).lastrowid
            group_id = db.execute("INSERT INTO conversations(kind,title) VALUES('group','گروه کارکنان')").lastrowid
            db.execute("INSERT INTO conversation_members(conversation_id,account_id) VALUES(?,?)", (group_id, owner_id))
        self.owner_id = owner_id

    def login(self, username="test_owner", password="Strong-Test-Owner-Password-2026!"):
        return self.client.post("/account/login", data={"username": username, "password": password}, follow_redirects=False)

    def test_public_pages_render(self):
        for path in ("/", "/account", "/account/login", "/account/register", "/news", "/academy", "/robots.txt", "/sitemap.xml"):
            with self.subTest(path=path):
                response = self.client.get(path)
                self.assertEqual(response.status_code, 200)

    def test_registration_and_shared_login(self):
        response = self.client.post("/account/register", data={
            "username": "new_player", "password": "Strong-Player-Password-2026!",
            "confirm_password": "Strong-Player-Password-2026!", "display_name": "New Player",
            "minecraft_username": "PlayerMC",
        }, follow_redirects=False)
        self.assertIn(response.status_code, (302, 303))
        login = self.client.post("/account/login", data={
            "username": "new_player", "password": "Strong-Player-Password-2026!"
        }, follow_redirects=False)
        self.assertIn(login.status_code, (302, 303))
        self.assertIn("/account/profile", login.headers["Location"])
        profile = self.client.get("/account/profile")
        self.assertEqual(profile.status_code, 200)
        self.assertIn("New Player", profile.get_data(as_text=True))

    def test_developer_can_promote_registered_account(self):
        self.client.post("/account/register", data={
            "username": "promote_me", "password": "Strong-Player-Password-2026!",
            "confirm_password": "Strong-Player-Password-2026!", "display_name": "Promote Me",
        })
        self.login()
        response = self.client.post("/staff/promote-member", data={"username": "promote_me", "role": "hbuilder"})
        self.assertIn(response.status_code, (302, 303))
        with site.connect_db() as db:
            account = db.execute("SELECT role,password_hash FROM accounts WHERE username='promote_me'").fetchone()
            self.assertEqual(account["role"], "hbuilder")
            self.assertTrue(site.check_password_hash(account["password_hash"], "Strong-Player-Password-2026!"))
            member = db.execute("SELECT 1 FROM conversation_members cm JOIN conversations c ON c.id=cm.conversation_id WHERE cm.account_id=(SELECT id FROM accounts WHERE username='promote_me') AND c.kind='group'").fetchone()
            self.assertIsNotNone(member)
        self.client.post("/account/logout")
        login = self.client.post("/account/login", data={
            "username": "promote_me", "password": "Strong-Player-Password-2026!"
        }, follow_redirects=False)
        self.assertIn("/account/profile", login.headers["Location"])
        profile = self.client.get("/account/profile")
        self.assertEqual(profile.status_code, 200)
        self.assertIn("داشبورد کارکنان", profile.get_data(as_text=True))
        self.assertEqual(self.client.get("/staff").status_code, 200)
        self.assertEqual(self.client.get("/staff?section=projects").status_code, 200)

    def test_project_capacity_and_builder_join(self):
        self.login()
        self.client.post("/projects/create", data={
            "title": "Spawn project", "description": "Build the new spawn", "required_builders": "1"
        })
        with site.connect_db() as db:
            project = db.execute("SELECT * FROM projects WHERE title='Spawn project'").fetchone()
            builder_id = db.execute("INSERT INTO accounts(username,password_hash,role,display_name) VALUES(?,?,?,?)",
                ("test_builder",site.generate_password_hash("Builder-Password-2026!"),"builder","Test Builder")).lastrowid
            group = db.execute("SELECT id FROM conversations WHERE kind='group' LIMIT 1").fetchone()
            db.execute("INSERT INTO conversation_members(conversation_id,account_id) VALUES(?,?)", (group["id"],builder_id))
        self.client.post("/account/logout")
        self.client.post("/account/login", data={"username":"test_builder","password":"Builder-Password-2026!"})
        response = self.client.post(f"/projects/{project['id']}/join")
        self.assertIn(response.status_code,(302,303))
        with site.connect_db() as db:
            updated = db.execute("SELECT status FROM projects WHERE id=?",(project["id"],)).fetchone()
            members = db.execute("SELECT COUNT(*) FROM project_members WHERE project_id=?",(project["id"],)).fetchone()[0]
        self.assertEqual(updated["status"],"Full")
        self.assertEqual(members,1)

    def test_minecraft_webhook_requires_token_and_tracks_presence(self):
        with site.connect_db() as db:
            builder_id = db.execute("INSERT INTO accounts(username,password_hash,role) VALUES(?,?,?)",
                ("minecraft_builder",site.generate_password_hash("Builder-Password-2026!"),"builder")).lastrowid
        bad = self.client.post("/api/minecraft-event", json={"username":"minecraft_builder","event":"join"})
        self.assertEqual(bad.status_code,401)
        good = self.client.post("/api/minecraft-event", headers={"X-MiladCraft-Token":"test-minecraft-token"},
            json={"username":"minecraft_builder","event":"join"})
        self.assertEqual(good.status_code,200)
        with site.connect_db() as db:
            presence = db.execute("SELECT is_online FROM staff_presence WHERE username='minecraft_builder'").fetchone()
            self.assertEqual(presence["is_online"],1)
        self.client.post("/api/minecraft-event", headers={"X-MiladCraft-Token":"test-minecraft-token"},
            json={"username":"minecraft_builder","event":"quit"})
        with site.connect_db() as db:
            presence = db.execute("SELECT is_online FROM staff_presence WHERE username='minecraft_builder'").fetchone()
            events = db.execute("SELECT COUNT(*) FROM staff_activity WHERE username='minecraft_builder'").fetchone()[0]
        self.assertEqual(presence["is_online"],0)
        self.assertEqual(events,2)

    def test_private_messages_are_visible_only_to_participants(self):
        with site.connect_db() as db:
            other_id = db.execute("INSERT INTO accounts(username,password_hash,role) VALUES(?,?,?)",
                ("other_builder",site.generate_password_hash("Builder-Password-2026!"),"builder")).lastrowid
            group = db.execute("SELECT id FROM conversations WHERE kind='group' LIMIT 1").fetchone()
            db.execute("INSERT INTO conversation_members(conversation_id,account_id) VALUES(?,?)",(group["id"],other_id))
        self.login()
        response = self.client.post("/messages/private",data={"recipient":"other_builder","body":"Private message"})
        self.assertIn(response.status_code,(302,303))
        with site.connect_db() as db:
            private = db.execute("SELECT id FROM conversations WHERE kind='private'").fetchone()
            member_count = db.execute("SELECT COUNT(*) FROM conversation_members WHERE conversation_id=?",(private["id"],)).fetchone()[0]
            message = db.execute("SELECT body FROM messages WHERE conversation_id=?",(private["id"],)).fetchone()
        self.assertEqual(member_count,2)
        self.assertEqual(message["body"],"Private message")


if __name__ == "__main__":
    unittest.main()
