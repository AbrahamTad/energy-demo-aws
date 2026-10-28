import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]


def load(name, relative):
    spec = importlib.util.spec_from_file_location(name, ROOT / relative)
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    return module


seed = load("seed", "scripts/aws/seed_public_energy.py")
smoke = load("smoke", "scripts/aws/publish_frontend.py")
guard = load("database_guard", "scripts/aws/check_plan.py")


class MigrationTests(unittest.TestCase):
    def test_seed_defaults_to_dry_run_without_aws_calls(self):
        with patch("sys.argv", ["seed_public_energy.py", "--file", str(ROOT / "scripts/aws/public_energy_seed.json"), "--account-id", "123456789012"]), patch("boto3.Session") as session:
            seed.main()
            session.assert_not_called()

    def test_seed_rejects_private_fields(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "seed.json"
            path.write_text(json.dumps({"records": [{"source": "Solar", "production": 1, "unit": "kWh", "user_sub": "private"}]}))
            with self.assertRaises(ValueError): seed.load_records(path)

    def test_public_smoke_accepts_empty_database_but_rejects_private_and_invalid_data(self):
        payload = {"project": "EnergyDemo", "status": "working", "records": []}
        smoke.verify_public_payload(payload)
        for record in [{"source": "Solar", "production": 1, "unit": "kWh", "user_sub": "private"},
                       {"source": "Solar", "production": float("nan"), "unit": "kWh"}]:
            with self.assertRaises(ValueError): smoke.verify_public_payload({**payload, "records": [record]})

    def test_plan_rejects_unapproved_table_names_and_disabled_protections(self):
        after = {"name": "energy-demo-aws-public-energy", "billing_mode": "PAY_PER_REQUEST", "deletion_protection_enabled": True,
                 "server_side_encryption": [{"enabled": True}], "point_in_time_recovery": [{"enabled": True}],
                 "on_demand_throughput": [{"max_read_request_units": 10, "max_write_request_units": 5}]}
        def plan(values): return {"resource_changes": [{"address": "aws_dynamodb_table.public_energy", "type": "aws_dynamodb_table", "change": {"actions": ["create"], "after": values}}]}
        guard.verify(plan(after), {})
        for changed in [{"name": "another-table"}, {"deletion_protection_enabled": False}, {"billing_mode": "PROVISIONED"},
                        {"server_side_encryption": [{"enabled": False}]}, {"point_in_time_recovery": [{"enabled": False}]}, {"on_demand_throughput": []}]:
            with self.subTest(changed=changed), self.assertRaises(ValueError): guard.verify(plan({**after, **changed}), {})
