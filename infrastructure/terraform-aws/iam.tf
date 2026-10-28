resource "aws_iam_role" "lambda" {
  name                 = "lambda-execution"
  path                 = "/energy-demo-aws/"
  permissions_boundary = local.boundary_arn
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow", Action = "sts:AssumeRole"
      Principal = { Service = "lambda.amazonaws.com" }
    }]
  })
}

resource "aws_iam_role_policy" "lambda_logs" {
  name = "energy-demo-logs"
  role = aws_iam_role.lambda.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = ["logs:CreateLogStream", "logs:PutLogEvents"]
      Resource = "${aws_cloudwatch_log_group.lambda.arn}:*"
    }]
  })
}

resource "aws_iam_role_policy" "public_energy" {
  name = "energy-demo-public-read"
  role = aws_iam_role.lambda.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow", Action = ["dynamodb:Query"]
      Resource  = aws_dynamodb_table.public_energy.arn
      Condition = { "ForAllValues:StringEquals" = { "dynamodb:LeadingKeys" = ["PUBLIC"] } }
    }]
  })
}

resource "aws_iam_role" "user_energy" {
  name                 = "user-energy-execution"
  path                 = "/energy-demo-aws/"
  permissions_boundary = local.user_boundary_arn
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow", Action = "sts:AssumeRole"
      Principal = { Service = "lambda.amazonaws.com" }
    }]
  })
}

resource "aws_iam_role_policy" "user_energy" {
  name = "energy-demo-user-records"
  role = aws_iam_role.user_energy.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      { Effect = "Allow", Action = ["logs:CreateLogStream", "logs:PutLogEvents"], Resource = "${aws_cloudwatch_log_group.user_energy.arn}:*" },
      { Effect = "Allow", Action = ["dynamodb:Query", "dynamodb:GetItem", "dynamodb:PutItem", "dynamodb:UpdateItem", "dynamodb:DeleteItem"], Resource = aws_dynamodb_table.user_energy.arn }
    ]
  })
}
