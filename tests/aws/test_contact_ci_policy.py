"""Offline evaluation of Contact CI policy templates; not an AWS IAM simulator.

The evaluator supports only the operators used by this module and fails on others.
Terraform mock tests separately verify real template rendering and attachments.
"""
import fnmatch
import json
from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parents[2]
MODULE = ROOT / "infrastructure/modules/contact-ci-policy"
ACCOUNT = "628582070745"
REGIONAL = "eu-north-1:" + ACCOUNT
PREFIX = "energy-demo-aws-contact"
KINDS = ["api", "relay", "worker", "admin", "events"]
FUNCTIONS = [f"arn:aws:lambda:{REGIONAL}:function:{PREFIX}-{k}" for k in KINDS]
ROLES = [f"arn:aws:iam::{ACCOUNT}:role/energy-demo-aws/contact-{k}" for k in KINDS]
KEY = f"arn:aws:kms:{REGIONAL}:key/11111111-1111-4111-8111-111111111111"
MAPPINGS = {"stream": "22222222-2222-4222-8222-222222222222", "queue": "33333333-3333-4333-8333-333333333333"}

def render():
    logs = [f"arn:aws:logs:{REGIONAL}:log-group:/aws/lambda/{PREFIX}-{k}" for k in KINDS]
    topic = f"arn:aws:sns:{REGIONAL}:{PREFIX}-events"
    updates = [{"Sid": "Contact"+k.title()+"MappingUpdate", "Effect": "Allow", "Action": ["lambda:UpdateEventSourceMapping"],
        "Resource": f"arn:aws:lambda:{REGIONAL}:event-source-mapping:{v}",
        "Condition": {"ArnEquals": {"lambda:FunctionArn": FUNCTIONS[1 if k == "stream" else 2]}}} for k,v in MAPPINGS.items()]
    alarms = [f"{PREFIX}-{k}-failures" for k in ["worker", "stream", "sns", "events"]]
    alarms += [f"{PREFIX}-{k}-errors" for k in ["worker", "reconcile", "events", "destination", "stream_destination", "schedule", "sns_redrive"]]
    alarms += [f"{PREFIX}-{k}" for k in ["uncertain-delivery", "failed-delivery", "reconcile-missing", "PendingJobs", "UnconfirmedJobs"]]
    values = {"function_arns": FUNCTIONS, "worker_function": FUNCTIONS[2], "events_function": FUNCTIONS[4], "relay_function": FUNCTIONS[1],
        "role_arns": ROLES, "mapping_arns": [f"arn:aws:lambda:{REGIONAL}:event-source-mapping:{MAPPINGS[k]}" for k in sorted(MAPPINGS)],
        "log_group_arns": logs, "log_stream_arns": [a+":*" for a in logs],
        "table_arn": f"arn:aws:dynamodb:{REGIONAL}:table/{PREFIX}",
        "queue_arns": [f"arn:aws:sqs:{REGIONAL}:{PREFIX}{k}" for k in [".fifo", "-dlq.fifo", "-stream-failures", "-sns-failures", "-event-processing-failures"]],
        "topic_arn": topic, "subscription_arn": topic+":*", "configuration_arn": f"arn:aws:ses:{REGIONAL}:configuration-set/{PREFIX}",
        "secret_arn": f"arn:aws:secretsmanager:{REGIONAL}:secret:energy-demo/contact-??????", "key_arn": KEY,
        "rule_arn": f"arn:aws:events:{REGIONAL}:rule/{PREFIX}-reconcile",
        "alarm_arns": [f"arn:aws:cloudwatch:{REGIONAL}:alarm:{a}" for a in alarms],
        "edge_arn": f"arn:aws:cloudfront::{ACCOUNT}:function/{PREFIX}-viewer"}

    context = {k:json.dumps(v) for k,v in values.items()}
    context["mapping_update_statements"] = ",".join(json.dumps(v) for v in updates)
    policies={}
    for p in MODULE.glob("*.json.tftpl"):
        template=p.read_text()
        template=re.sub(r'%\{ if mapping_update_statements != "" \}|%\{ endif \}', '', template)
        policies[p.name.removesuffix('.json.tftpl')]=json.loads(re.sub(r'\$\{([a-z_]+)\}',lambda m:context[m[1]],template))
    return policies, values

def allowed(policies, action, resource, context=None):
    context=context or {}
    found=False
    for policy in policies:
        for statement in policy["Statement"]:
            actions=statement["Action"]; resources=statement["Resource"]
            if isinstance(actions,str): actions=[actions]
            if isinstance(resources,str): resources=[resources]
            if not any(fnmatch.fnmatchcase(action.lower(),a.lower()) for a in actions) or not any(fnmatch.fnmatchcase(resource,r) for r in resources): continue
            matches=True
            for operator,conditions in statement.get("Condition",{}).items():
                if operator not in ["StringEquals","ArnEquals"]: raise AssertionError("Unsupported IAM operator")
                for key, expected in conditions.items():
                    if not isinstance(expected,list): expected=[expected]
                    matches &= context.get(key) in expected
            if not matches:continue
            if statement["Effect"] == "Deny":return False
            if statement["Effect"] != "Allow":raise AssertionError("Unsupported effect")
            found=True
    return found

class ContactCIPolicyTests(unittest.TestCase):
    def setUp(self):
        self.p,self.v=render()
        self.plan=[self.p[k] for k in ["read-runtime","read-delivery","guard"]]
        self.deploy=list(self.p.values())

    def test_plan_reads_exact_contact_metadata_only(self):
        for action,resource in [("lambda:GetFunction",FUNCTIONS[0]),("dynamodb:DescribeTable",self.v["table_arn"]),
                ("sqs:GetQueueAttributes",self.v["queue_arns"][0]),("kms:GetKeyPolicy",KEY),
                ("secretsmanager:DescribeSecret",self.v["secret_arn"].replace("??????","ABC123"))]:
            self.assertTrue(allowed(self.plan,action,resource))
        for action,resource in [("lambda:UpdateFunctionCode",FUNCTIONS[0]),("dynamodb:CreateTable",self.v["table_arn"]),
                ("lambda:GetFunction",FUNCTIONS[0]+"-unapproved"),("kms:DescribeKey",KEY.replace("11111111","99999999"))]:
            self.assertFalse(allowed(self.plan,action,resource))

    def test_create_role_denied_even_with_correct_boundary_and_accidental_grant(self):
        accidental={"Statement":[{"Effect":"Allow","Action":"*","Resource":"*"}]}
        for k,role in zip(KINDS,ROLES):
            own=f"arn:aws:iam::{ACCOUNT}:policy/energy-demo-bootstrap/contact-{k}-boundary"
            for boundary in [None,own,own+"-unapproved"]:
                for policies in [self.plan,self.deploy,[*self.deploy,accidental]]:
                    self.assertFalse(allowed(policies,"iam:CreateRole",role,{"iam:PermissionsBoundary":boundary}))
            self.assertFalse(allowed(self.deploy,"iam:PutRolePolicy",role))
            self.assertFalse(allowed(self.deploy,"iam:PassRole",role,{"iam:PassedToService":"lambda.amazonaws.com"}))
            for service in [None,"ec2.amazonaws.com","ecs-tasks.amazonaws.com"]:
                self.assertFalse(allowed(self.deploy,"iam:PassRole",role,{"iam:PassedToService":service}))
        other=f"arn:aws:iam::{ACCOUNT}:role/energy-demo-bootstrap/github-deploy"
        self.assertFalse(allowed(self.deploy,"iam:PassRole",other,{"iam:PassedToService":"lambda.amazonaws.com"}))
        self.assertFalse(allowed(self.deploy,"iam:PutRolePolicy",other))

    def test_deploy_scopes_updates_and_mapping_function_pairs(self):
        for action,resource in [("lambda:UpdateFunctionCode",FUNCTIONS[0]),("dynamodb:UpdateTimeToLive",self.v["table_arn"]),
                ("sqs:SetQueueAttributes",self.v["queue_arns"][0]),("cloudwatch:PutMetricAlarm",self.v["alarm_arns"][0])]:
            self.assertTrue(allowed(self.deploy,action,resource))
            self.assertFalse(allowed(self.deploy,action,resource+"-unapproved"))
        for k,id in MAPPINGS.items():
            arn=f"arn:aws:lambda:{REGIONAL}:event-source-mapping:{id}"
            expected=FUNCTIONS[1 if k=="stream" else 2]
            self.assertFalse(allowed(self.deploy,"lambda:UpdateEventSourceMapping",arn,{"lambda:FunctionArn":expected}))
            self.assertFalse(allowed(self.deploy,"lambda:UpdateEventSourceMapping",arn,{"lambda:FunctionArn":FUNCTIONS[0]}))
            self.assertFalse(allowed(self.deploy,"lambda:UpdateEventSourceMapping",arn.replace(id,"99999999-9999-4999-8999-999999999999"),{"lambda:FunctionArn":expected}))

    def test_services_must_target_contact_functions(self):
        for service in ["apigateway.amazonaws.com","sns.amazonaws.com","events.amazonaws.com"]:
            self.assertFalse(allowed(self.deploy,"lambda:AddPermission",FUNCTIONS[0],{"lambda:Principal":service}))
        self.assertFalse(allowed(self.deploy,"lambda:AddPermission",FUNCTIONS[0],{"lambda:Principal":"*"}))
        ctx={"sns:Protocol":"lambda","sns:Endpoint":FUNCTIONS[4]}
        self.assertTrue(allowed(self.deploy,"sns:Subscribe",self.v["topic_arn"],ctx))
        self.assertFalse(allowed(self.deploy,"sns:Subscribe",self.v["topic_arn"],{**ctx,"sns:Protocol":"email"}))
        self.assertFalse(allowed(self.deploy,"sns:Subscribe",self.v["topic_arn"],{**ctx,"sns:Endpoint":FUNCTIONS[0]}))
        self.assertTrue(allowed(self.deploy,"events:PutTargets",self.v["rule_arn"],{"events:TargetArn":FUNCTIONS[1]}))
        self.assertFalse(allowed(self.deploy,"events:PutTargets",self.v["rule_arn"],{"events:TargetArn":FUNCTIONS[2]}))

    def test_explicit_denies_win_over_accidental_grants(self):
        accidental={"Statement":[{"Effect":"Allow","Action":"*","Resource":"*"}]}
        cases=["iam:CreateRole","iam:PutRolePermissionsBoundary","secretsmanager:GetSecretValue","secretsmanager:BatchGetSecretValue","secretsmanager:CreateSecret",
            "dynamodb:GetItem","dynamodb:Scan","dynamodb:PartiQLSelect","dynamodb:UpdateItem","sqs:ReceiveMessage","sqs:SendMessage",
            "ses:SendEmail","ses:SendRawEmail","ses:SendBulkEmail","sns:Publish","lambda:InvokeFunction","sts:AssumeRole",
            "iam:CreatePolicyVersion","iam:AttachRolePolicy","iam:UpdateAssumeRolePolicy","iam:DeleteRolePermissionsBoundary",
            "kms:CreateKey","kms:PutKeyPolicy","kms:CreateGrant","kms:Decrypt","kms:ScheduleKeyDeletion","lambda:CreateEventSourceMapping"]
        for action in cases:
            with self.subTest(action=action):self.assertFalse(allowed([accidental,self.p["guard"]],action,"*"))

    def test_no_deletion_or_unconstrained_allow_and_managed_policy_limits(self):
        for name,policy in self.p.items():
            self.assertLessEqual(len(json.dumps(policy,separators=(",",":"))),6144,name)
            for st in policy["Statement"]:
                if st["Effect"] != "Allow":continue
                resources=st["Resource"] if isinstance(st["Resource"],list) else [st["Resource"]]
                self.assertTrue(all(r and r!="*" for r in resources))
                self.assertTrue(all(not re.search(r":(Delete|Remove|Purge|Send|Invoke|Assume|Attach)",a) for a in st["Action"]))
        self.assertFalse(allowed(self.deploy,"cloudfront:UpdateDistribution",f"arn:aws:cloudfront::{ACCOUNT}:distribution/UNAPPROVED"))

    def test_saved_plan_rejects_runtime_trust_boundary_and_role_escalation(self):
        import copy
        from test_deployment import plan_guard
        role={"address": 'aws_iam_role.contact["api"]', "change": {"actions": ["no-op"], "after": {
            "name": "contact-api", "path": "/energy-demo-aws/",
            "permissions_boundary": f"arn:aws:iam::{ACCOUNT}:policy/energy-demo-bootstrap/contact-api-boundary",
            "assume_role_policy": json.dumps({"Version":"2012-10-17","Statement":[{"Effect":"Allow","Action":"sts:AssumeRole","Principal":{"Service":"lambda.amazonaws.com"}}]})}}}
        plan_guard.verify({"resource_changes":[role]}, {})
        creating=copy.deepcopy(role);creating["change"]["actions"]=["create"]
        with self.assertRaises(ValueError):plan_guard.verify({"resource_changes":[creating]}, {})
        for key,value in [("name","github-deploy"),("path","/energy-demo-bootstrap/"),("permissions_boundary",""),
                ("assume_role_policy",json.dumps({"Version":"2012-10-17","Statement":[{"Effect":"Allow","Action":"sts:AssumeRole","Principal":{"AWS":"*"}}]}))]:
            bad=copy.deepcopy(role);bad["change"]["after"][key]=value
            with self.subTest(key=key),self.assertRaises(ValueError):plan_guard.verify({"resource_changes":[bad]}, {})
        function={"address": 'aws_lambda_function.contact["api"]',"change":{"actions":["no-op"],"after":{"role":ROLES[0]}}}
        plan_guard.verify({"resource_changes":[function]}, {})
        function["change"]["after"]["role"]=ROLES[2]
        with self.assertRaises(ValueError):plan_guard.verify({"resource_changes":[function]}, {})

    def test_operator_only_writes_denied_even_with_accidental_allow(self):
        accidental={"Statement":[{"Effect":"Allow","Action":"*","Resource":"*"}]}
        for policies in [self.plan,self.deploy,[accidental,self.p["guard"]]]:
            for role in ROLES:
                for action in ["iam:PutRolePolicy","iam:DeleteRolePolicy","iam:PassRole"]:
                    for service in ["lambda.amazonaws.com","ec2.amazonaws.com"]:
                        self.assertFalse(allowed(policies,action,role,{"iam:PassedToService":service}))
            for function in FUNCTIONS:
                for action in ["lambda:CreateFunction","lambda:UpdateFunctionConfiguration","lambda:PutFunctionConcurrency","lambda:DeleteFunctionConcurrency","lambda:AddPermission","lambda:PutFunctionEventInvokeConfig","lambda:UpdateFunctionEventInvokeConfig"]:
                    self.assertFalse(allowed(policies,action,function))
            for mapping in self.v["mapping_arns"]:
                self.assertFalse(allowed(policies,"lambda:UpdateEventSourceMapping",mapping))
        # New scoped denies must not silently disable unrelated base deployment rights.
        unrelated="arn:aws:iam::"+ACCOUNT+":role/energy-demo-aws/lambda-execution"
        self.assertTrue(allowed([accidental,self.p["guard"]],"iam:PassRole",unrelated))

    def test_code_updates_are_trusted_authority_not_a_data_isolation_boundary(self):
        from test_deployment import plan_guard
        import copy
        self.assertTrue(allowed(self.deploy,"lambda:UpdateFunctionCode",FUNCTIONS[0]))
        self.assertFalse(allowed(self.deploy,"lambda:UpdateFunctionCode",FUNCTIONS[0]+"-other"))
        self.assertFalse(allowed(self.plan,"lambda:UpdateFunctionCode",FUNCTIONS[0]))
        for action,resource in [("secretsmanager:GetSecretValue",self.v["secret_arn"]),("dynamodb:GetItem",self.v["table_arn"])]:
            self.assertFalse(allowed(self.deploy,action,resource))
        # The runtime ceiling still permits secret/record reads: caller denies do not transfer.
        text=(ROOT/"infrastructure/modules/contact-policy/main.tf").read_text()
        self.assertIn('"secretsmanager:GetSecretValue"',text)
        self.assertIn('"dynamodb:GetItem"',text)
        before={"role":ROLES[0],"handler":"contact_api.lambda_handler","environment":[{"variables":{"CONTACT_SECRET_ARN":"metadata-only"}}],"runtime":"python3.12","layers":[],"source_code_hash":"old"}
        after=copy.deepcopy(before);after["source_code_hash"]="new"
        resource={"address":'aws_lambda_function.contact["api"]',"change":{"actions":["update"],"before":before,"after":after}}
        plan_guard.verify({"resource_changes":[resource]}, {})
        for key,value in [("environment",[]),("role",ROLES[1]),("handler","other.handler"),("runtime","other"),("layers",["unreviewed"])]:
            bad=copy.deepcopy(resource);bad["change"]["after"][key]=value
            with self.subTest(key=key),self.assertRaises(ValueError):plan_guard.verify({"resource_changes":[bad]}, {})
        bad=copy.deepcopy(resource);bad["change"]["after_unknown"]={"environment":True}
        with self.assertRaises(ValueError):plan_guard.verify({"resource_changes":[bad]}, {})
        for address in ['aws_iam_role_policy.contact["api"]','aws_lambda_event_source_mapping.contact_queue[0]']:
            bad={"address":address,"change":{"actions":["update"],"after":{}}}
            with self.assertRaises(ValueError):plan_guard.verify({"resource_changes":[bad]}, {})
