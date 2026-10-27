# Administrator-only bootstrap. Never applied by the GitHub deployment role.
terraform {
  required_version = "= 1.16.5"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "= 6.69.1"
    }
  }
  backend "local" { path = "../../.local/terraform-aws-bootstrap.tfstate" }
}

variable "account_id" {
  type = string
  validation {
    condition     = can(regex("^[0-9]{12}$", var.account_id)) && var.account_id != "000000000000"
    error_message = "A real, explicitly approved AWS account is required."
  }
}

variable "github_subject_prefix" {
  type        = string
  description = "Verified OIDC prefix, including trailing colon; supports immutable GitHub IDs."
  validation {
    condition     = can(regex("^repo:AbrahamTad(@[0-9]+)?/energy-demo-aws(@[0-9]+)?:$", var.github_subject_prefix))
    error_message = "Supply the verified subject prefix for AbrahamTad/energy-demo-aws only."
  }
}

variable "existing_oidc_provider_arn" {
  type        = string
  default     = ""
  description = "Reuse an existing account-wide GitHub provider instead of replacing it."
  validation {
    condition     = var.existing_oidc_provider_arn == "" || var.existing_oidc_provider_arn == "arn:aws:iam::${var.account_id}:oidc-provider/token.actions.githubusercontent.com"
    error_message = "Existing provider must belong to the approved account and GitHub issuer."
  }
}

variable "deployment_resource_ids" {
  description = "Administrator-verified IDs from the initial EnergyDemo stack. Null disables all API/CloudFront mutation access."
  type = object({
    api_id                     = string
    cloudfront_distribution_id = string
    cloudfront_oac_id          = string
  })
  default = null
  validation {
    condition = var.deployment_resource_ids == null || (
      can(regex("^[a-z0-9]{1,32}$", var.deployment_resource_ids.api_id)) &&
      can(regex("^[A-Z0-9]{1,64}$", var.deployment_resource_ids.cloudfront_distribution_id)) &&
      can(regex("^[A-Z0-9]{1,64}$", var.deployment_resource_ids.cloudfront_oac_id))
    )
    error_message = "Supply exact reviewed resource IDs, never ARNs, paths or wildcards."
  }
}

provider "aws" {
  region              = "eu-north-1"
  allowed_account_ids = [var.account_id]
  default_tags { tags = { Project = "EnergyDemo", Environment = "AWS", ManagedBy = "Terraform" } }
}

locals {
  bucket        = "energy-demo-tfstate-${var.account_id}-eu-north-1"
  state_key     = "energy-demo/aws/terraform.tfstate"
  frontend_arn  = "arn:aws:s3:::energy-demo-aws-${var.account_id}-eu-north-1"
  execution_arn = "arn:aws:iam::${var.account_id}:role/energy-demo-aws/lambda-execution"
  lambda_arn    = "arn:aws:lambda:eu-north-1:${var.account_id}:function:energy-demo-aws-energy"
  # Resource tagging APIs require the exact ARN, without the :* suffix.
  log_group_arns = [
    "arn:aws:logs:eu-north-1:${var.account_id}:log-group:/aws/lambda/energy-demo-aws-energy",
    "arn:aws:logs:eu-north-1:${var.account_id}:log-group:/energy-demo-aws/http-api"
  ]
  log_arns = [for arn in local.log_group_arns : "${arn}:*"]
  oidc_arn = var.existing_oidc_provider_arn != "" ? var.existing_oidc_provider_arn : aws_iam_openid_connect_provider.github[0].arn
  subjects = {
    plan   = "${var.github_subject_prefix}ref:refs/heads/main"
    deploy = "${var.github_subject_prefix}environment:aws-production"
  }
}

resource "aws_s3_bucket" "state" {
  bucket        = local.bucket
  force_destroy = false
  lifecycle { prevent_destroy = true }
}
resource "aws_s3_bucket_public_access_block" "state" {
  bucket                  = aws_s3_bucket.state.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}
resource "aws_s3_bucket_ownership_controls" "state" {
  bucket = aws_s3_bucket.state.id
  rule { object_ownership = "BucketOwnerEnforced" }
}
resource "aws_s3_bucket_versioning" "state" {
  bucket = aws_s3_bucket.state.id
  versioning_configuration { status = "Enabled" }
}
resource "aws_s3_bucket_server_side_encryption_configuration" "state" {
  bucket = aws_s3_bucket.state.id
  rule {
    apply_server_side_encryption_by_default { sse_algorithm = "AES256" }
  }
}
resource "aws_s3_bucket_policy" "state" {
  bucket = aws_s3_bucket.state.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Sid       = "RequireTLS", Effect = "Deny", Principal = "*", Action = "s3:*"
      Resource  = [aws_s3_bucket.state.arn, "${aws_s3_bucket.state.arn}/*"]
      Condition = { Bool = { "aws:SecureTransport" = "false" } }
    }]
  })
}

resource "aws_iam_openid_connect_provider" "github" {
  count          = var.existing_oidc_provider_arn == "" ? 1 : 0
  url            = "https://token.actions.githubusercontent.com"
  client_id_list = ["sts.amazonaws.com"]
}

resource "aws_iam_policy" "lambda_boundary" {
  name = "lambda-logs-boundary"
  path = "/energy-demo-bootstrap/"
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow", Action = ["logs:CreateLogStream", "logs:PutLogEvents"]
      Resource = local.log_arns[0]
    }]
  })
}

resource "aws_iam_role" "github" {
  for_each             = local.subjects
  name                 = "github-${each.key}"
  path                 = "/energy-demo-bootstrap/"
  max_session_duration = 3600
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow", Action = "sts:AssumeRoleWithWebIdentity"
      Principal = { Federated = local.oidc_arn }
      Condition = { StringEquals = {
        "token.actions.githubusercontent.com:aud" = "sts.amazonaws.com"
        "token.actions.githubusercontent.com:sub" = each.value
      } }
    }]
  })
}

# Initial API/CloudFront creation is administrator-only. CI receives exact IDs
# after that separate, reviewed operation; it cannot create or replace them.
locals {
  api_root_arns = var.deployment_resource_ids == null ? [] : [
    "arn:aws:apigateway:eu-north-1::/apis/${var.deployment_resource_ids.api_id}"
  ]
  api_child_arns = [for arn in local.api_root_arns : "${arn}/*"]
  api_tag_arns   = [for arn in local.api_root_arns : "arn:aws:apigateway:eu-north-1::/tags/${urlencode(arn)}"]
  distribution_arns = var.deployment_resource_ids == null ? [] : [
    "arn:aws:cloudfront::${var.account_id}:distribution/${var.deployment_resource_ids.cloudfront_distribution_id}"
  ]
  oac_arns = var.deployment_resource_ids == null ? [] : [
    "arn:aws:cloudfront::${var.account_id}:origin-access-control/${var.deployment_resource_ids.cloudfront_oac_id}"
  ]
  read_statements = [
    { Effect = "Allow", Action = ["s3:Get*", "s3:ListBucket"], Resource = [local.frontend_arn, "${local.frontend_arn}/*"] },
    { Effect = "Allow", Action = ["lambda:GetFunction", "lambda:GetFunctionConfiguration", "lambda:GetFunctionCodeSigningConfig", "lambda:GetPolicy", "lambda:ListVersionsByFunction", "lambda:ListTags"], Resource = [local.lambda_arn] },
    { Effect = "Allow", Action = ["iam:GetRole", "iam:GetRolePolicy", "iam:ListRolePolicies", "iam:ListAttachedRolePolicies", "iam:ListInstanceProfilesForRole"], Resource = [local.execution_arn] },
    { Effect = "Allow", Action = ["logs:DescribeLogGroups"], Resource = ["*"], Condition = { StringEquals = { "aws:RequestedRegion" = "eu-north-1" } } },
    { Effect = "Allow", Action = ["logs:ListTagsForResource"], Resource = local.log_group_arns },
    { Effect = "Allow", Action = ["logs:ListTagsLogGroup"], Resource = local.log_arns },
    { Effect = "Allow", Action = ["apigateway:GET"], Resource = concat(local.api_root_arns, local.api_child_arns, local.api_tag_arns) },
    { Effect = "Allow", Action = ["cloudfront:GetDistribution", "cloudfront:GetDistributionConfig", "cloudfront:ListTagsForResource"], Resource = local.distribution_arns },
    { Effect = "Allow", Action = ["cloudfront:GetOriginAccessControl", "cloudfront:GetOriginAccessControlConfig"], Resource = local.oac_arns },
    { Effect = "Allow", Action = ["cloudfront:GetInvalidation"], Resource = local.distribution_arns },
    { Effect = "Allow", Action = ["budgets:ViewBudget", "budgets:ListTagsForResource"], Resource = ["arn:aws:budgets::${var.account_id}:budget/energy-demo-aws-monthly"] }
  ]
  write_statements = [
    { Effect = "Allow", Action = ["s3:CreateBucket", "s3:DeleteBucket", "s3:PutBucketPolicy", "s3:DeleteBucketPolicy", "s3:PutBucketPublicAccessBlock", "s3:PutBucketOwnershipControls", "s3:DeleteBucketOwnershipControls", "s3:PutEncryptionConfiguration", "s3:PutBucketTagging"], Resource = [local.frontend_arn] },
    { Effect = "Allow", Action = ["s3:PutObject", "s3:DeleteObject"], Resource = ["${local.frontend_arn}/*"] },
    { Effect = "Allow", Action = ["lambda:CreateFunction", "lambda:UpdateFunctionCode", "lambda:UpdateFunctionConfiguration", "lambda:DeleteFunction", "lambda:AddPermission", "lambda:RemovePermission", "lambda:TagResource", "lambda:UntagResource", "lambda:PutFunctionConcurrency", "lambda:DeleteFunctionConcurrency"], Resource = [local.lambda_arn] },
    { Effect = "Allow", Action = ["iam:CreateRole"], Resource = [local.execution_arn], Condition = { StringEquals = { "iam:PermissionsBoundary" = aws_iam_policy.lambda_boundary.arn } } },
    { Effect = "Allow", Action = ["iam:DeleteRole", "iam:PutRolePolicy", "iam:DeleteRolePolicy", "iam:TagRole", "iam:UntagRole"], Resource = [local.execution_arn] },
    { Effect = "Allow", Action = ["iam:PassRole"], Resource = [local.execution_arn], Condition = { StringEquals = { "iam:PassedToService" = "lambda.amazonaws.com" } } },
    { Effect = "Allow", Action = ["logs:TagResource", "logs:UntagResource"], Resource = local.log_group_arns },
    { Effect = "Allow", Action = ["logs:CreateLogGroup", "logs:DeleteLogGroup", "logs:PutRetentionPolicy", "logs:DeleteRetentionPolicy", "logs:TagLogGroup", "logs:UntagLogGroup"], Resource = local.log_arns },
    { Effect = "Allow", Action = ["apigateway:PATCH"], Resource = local.api_root_arns },
    { Effect = "Allow", Action = ["apigateway:POST", "apigateway:PATCH", "apigateway:PUT", "apigateway:DELETE"], Resource = local.api_child_arns },
    { Effect = "Allow", Action = ["cloudfront:UpdateDistribution", "cloudfront:CreateInvalidation"], Resource = local.distribution_arns },
    { Effect = "Allow", Action = ["cloudfront:UpdateOriginAccessControl"], Resource = local.oac_arns },
  ]
}

resource "aws_iam_role_policy" "github" {
  for_each = local.subjects
  name     = "energy-demo-${each.key}"
  role     = aws_iam_role.github[each.key].id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = concat(
      [for statement in local.read_statements : statement if length(statement.Resource) > 0],
      [for statement in local.write_statements : statement if each.key == "deploy" && length(statement.Resource) > 0], [
        {
          Effect = "Allow", Action = ["s3:ListBucket", "s3:GetBucketLocation"], Resource = [aws_s3_bucket.state.arn]
        },
        {
          Effect   = "Allow", Action = each.key == "deploy" ? ["s3:GetObject", "s3:PutObject"] : ["s3:GetObject"]
          Resource = ["${aws_s3_bucket.state.arn}/${local.state_key}"]
        },
        {
          Effect   = "Allow", Action = ["s3:GetObject", "s3:PutObject", "s3:DeleteObject"]
          Resource = ["${aws_s3_bucket.state.arn}/${local.state_key}.tflock"]
        }
    ])
  })
}

output "state_bucket" { value = aws_s3_bucket.state.id }
output "plan_role_arn" { value = aws_iam_role.github["plan"].arn }
output "deploy_role_arn" { value = aws_iam_role.github["deploy"].arn }
