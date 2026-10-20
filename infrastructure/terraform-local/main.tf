# A separate S3 bucket managed by Terraform
resource "aws_s3_bucket" "energy_test" {
  bucket = "energy-demo-terraform-test"

  tags = {
    Project     = "EnergyDemo"
    Environment = "Local"
    ManagedBy   = "Terraform"
  }
}


# Python Lambda managed by Terraform
resource "aws_lambda_function" "energy" {
  function_name = "energy-demo-terraform-function"

  # Python deployment package
  filename         = "../../lambda/energy/energy-lambda.zip"
  source_code_hash = filebase64sha256("../../lambda/energy/energy-lambda.zip")

  # Lambda configuration
  handler = "handler.lambda_handler"
  runtime = "python3.12"

  # Local Floci testing role
  role = "arn:aws:iam::000000000000:role/energy-demo-lambda-role"

  timeout     = 10
  memory_size = 128

  tags = {
    Project     = "EnergyDemo"
    Environment = "Local"
    ManagedBy   = "Terraform"
  }
}


# =========================================
# API Gateway for EnergyDemo
# =========================================

# Create a REST API
resource "aws_api_gateway_rest_api" "energy" {
  name        = "energy-demo-terraform-api"
  description = "EnergyDemo API managed by Terraform"

  endpoint_configuration {
    types = ["REGIONAL"]
  }
}

# Create /api
resource "aws_api_gateway_resource" "api" {
  rest_api_id = aws_api_gateway_rest_api.energy.id
  parent_id   = aws_api_gateway_rest_api.energy.root_resource_id
  path_part   = "api"
}

# Create /api/energy
resource "aws_api_gateway_resource" "energy" {
  rest_api_id = aws_api_gateway_rest_api.energy.id
  parent_id   = aws_api_gateway_resource.api.id
  path_part   = "energy"
}

# Allow GET requests to /api/energy
resource "aws_api_gateway_method" "energy_get" {
  rest_api_id   = aws_api_gateway_rest_api.energy.id
  resource_id   = aws_api_gateway_resource.energy.id
  http_method   = "GET"
  authorization = "NONE"
}