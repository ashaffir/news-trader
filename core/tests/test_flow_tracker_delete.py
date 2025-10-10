from django.test import TestCase
from django.urls import reverse
from django.contrib.auth.models import User

from core.models import Source, Post, Analysis


class FlowTrackerDeleteApiTests(TestCase):
    def setUp(self):
        # Create staff user and login
        self.user = User.objects.create_user("admin", password="x", is_staff=True)
        self.client.force_login(self.user)

        # Minimal objects to back Analyses
        self.source = Source.objects.create(name="Test", url="https://example.com/a")
        self.post1 = Post.objects.create(source=self.source, content="c1", url="https://example.com/p1")
        self.post2 = Post.objects.create(source=self.source, content="c2", url="https://example.com/p2")
        self.a1 = Analysis.objects.create(post=self.post1, symbol="ABC", direction="buy", confidence=0.9, reason="r")
        self.a2 = Analysis.objects.create(post=self.post2, symbol="XYZ", direction="sell", confidence=0.8, reason="r")

    def test_delete_multiple_analyses(self):
        url = reverse("api_flow_delete")
        resp = self.client.post(url, data={"ids": [self.a1.id, self.a2.id]}, content_type="application/json")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data.get("success"))
        # Both should be deleted
        self.assertFalse(Analysis.objects.filter(id__in=[self.a1.id, self.a2.id]).exists())

    def test_delete_requires_ids(self):
        url = reverse("api_flow_delete")
        resp = self.client.post(url, data={}, content_type="application/json")
        self.assertEqual(resp.status_code, 400)
        self.assertIn("error", resp.json())


