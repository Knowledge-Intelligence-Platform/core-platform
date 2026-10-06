data "aws_availability_zones" "available" {
  state = "available"
}

locals {
  network_azs = slice(data.aws_availability_zones.available.names, 0, length(var.public_subnet_cidrs))
}

resource "aws_vpc" "this" {
  cidr_block           = var.vpc_cidr
  enable_dns_support   = true
  enable_dns_hostnames = true

  tags = {
    Name      = local.name_prefix
    Component = "network"
  }
}

resource "aws_internet_gateway" "this" {
  vpc_id = aws_vpc.this.id

  tags = {
    Name      = "${local.name_prefix}-igw"
    Component = "network"
  }
}

resource "aws_subnet" "public" {
  count = length(local.network_azs)

  vpc_id                  = aws_vpc.this.id
  cidr_block              = var.public_subnet_cidrs[count.index]
  availability_zone       = local.network_azs[count.index]
  map_public_ip_on_launch = true

  tags = {
    Name      = "${local.name_prefix}-public-${count.index + 1}"
    Component = "network"
    Tier      = "public"
  }
}

resource "aws_route_table" "public" {
  vpc_id = aws_vpc.this.id

  tags = {
    Name      = "${local.name_prefix}-public"
    Component = "network"
    Tier      = "public"
  }
}

resource "aws_route" "public_internet" {
  route_table_id         = aws_route_table.public.id
  destination_cidr_block = "0.0.0.0/0"
  gateway_id             = aws_internet_gateway.this.id
}

resource "aws_route_table_association" "public" {
  count = length(local.network_azs)

  subnet_id      = aws_subnet.public[count.index].id
  route_table_id = aws_route_table.public.id
}
