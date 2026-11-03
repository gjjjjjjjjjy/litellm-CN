"""Previously saved personal image runs remain readable after removing personal keys."""

import asyncio
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from fastapi import HTTPException

from litellm.proxy._types import LitellmUserRoles
from litellm.proxy.management_endpoints import qos_images


class LegacyImageRunTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.root = Path(self.directory.name)
        self.root_patch = patch.object(qos_images, "RESULTS_ROOT", self.root)
        self.root_patch.start()

    def tearDown(self):
        self.root_patch.stop()
        self.directory.cleanup()

    def test_old_personal_run_retains_owner_access_and_rating(self):
        original = qos_images.ImageRun(
            id="img-0123456789abcdef", model="Qwen-Image-2512", status="complete",
            started_at=datetime.now(timezone.utc), concurrency=1, size="1024x1024",
            unit_cost_cny=0.03, estimated_cost_cny=0.03, owner_user_id="alice",
            personal_kind="sync", items=(qos_images.ImageItem(
                id="0001", prompt_id="p", prompt="A red apple", check="", seed=1,
                status="success", rating=qos_images.ImageRating(
                    prompt_adherence=4, structure_correctness=4, image_quality=4,
                    visual_appeal=4, hard_conditions_passed=True, text_applicable=False,
                ),
            ),),
        )
        qos_images._write_run(original)
        restored = qos_images._read_run(original.id)
        self.assertEqual(restored.owner_user_id, "alice")
        self.assertEqual(restored.personal_kind, "sync")
        self.assertEqual(restored.items[0].rating.quality_score, 75.0)
        alice = SimpleNamespace(user_role=LitellmUserRoles.INTERNAL_USER, user_id="alice")
        bob = SimpleNamespace(user_role=LitellmUserRoles.INTERNAL_USER, user_id="bob")
        qos_images._authorize_run(restored, alice, write=True)
        with self.assertRaises(HTTPException) as denied:
            qos_images._authorize_run(restored, bob)
        self.assertEqual(denied.exception.status_code, 404)

        now = datetime.now(timezone.utc)
        own = qos_images.summarize_image_runs(self.root, now - timedelta(hours=24), now,
                                              user_id="alice", include_legacy=False)
        other = qos_images.summarize_image_runs(self.root, now - timedelta(hours=24), now,
                                                user_id="bob", include_legacy=False)
        self.assertEqual(own.requests, 1)
        self.assertEqual(other.requests, 0)

    def test_personal_key_save_route_is_absent(self):
        self.assertNotIn("/qos/images/personal-models", {route.path for route in qos_images.router.routes})

    def test_run_list_filters_by_start_time_before_limiting_results(self):
        now = datetime.now(timezone.utc)
        for index, age in enumerate((timedelta(minutes=5), timedelta(hours=2)), start=1):
            qos_images._write_run(qos_images.ImageRun(
                id=f"img-{index:016x}", model="Qwen-Image-2512", status="complete",
                started_at=now - age, concurrency=1, size="1024x1024",
                unit_cost_cny=0.03, estimated_cost_cny=0.03, items=(),
            ))
        admin = SimpleNamespace(user_role=LitellmUserRoles.PROXY_ADMIN, user_id="admin")
        recent = asyncio.run(qos_images.list_image_runs(admin, "1h"))
        all_runs = asyncio.run(qos_images.list_image_runs(admin))
        self.assertEqual([run.id for run in recent], ["img-0000000000000001"])
        self.assertEqual(len(all_runs), 2)


if __name__ == "__main__":
    unittest.main()
