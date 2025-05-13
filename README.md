<!-- omit in toc -->
# Migrating to the AWS Load Balancer Controller

- [Introduction](#introduction)
- [Prerequisites](#prerequisites)
- [Create and configure the EKS cluster](#create-and-configure-the-eks-cluster)
    - [Install the AWS Load Balancer Controller](#install-the-aws-load-balancer-controller)
- [Scenarios](#scenarios)
  - [1. Application Load Balancer (ALB) with combined Ingress and ACM certificates](#1-application-load-balancer-alb-with-combined-ingress-and-acm-certificates)
    - [Create resources](#create-resources)
    - [Validate resources](#validate-resources)
  - [Deploy the echoserver resources](#deploy-the-echoserver-resources)
  - [External ALB](#external-alb)
  - [Scenarios](#scenarios-1)
    - [03 IngressGroup](#03-ingressgroup)
    - [04 TargetGroupBinding](#04-targetgroupbinding)
  - [Delete the cluster](#delete-the-cluster)


# Introduction

Caktus uses the [NGINX Ingress
Controller](https://github.com/kubernetes/ingress-nginx) to manage ingress
traffic in our Kubernetes clusters. In AWS, we use a [Network load balancer
(NLB)](https://docs.aws.amazon.com/elasticloadbalancing/latest/network/introduction.html)
to expose the controller behind a Service of ``Type=LoadBalancer``. By default,
this uses the legacy "in-tree" (within ingress-nginx itself) service load
balancer to create and manage the NLB, but the controller doesn't support
[associating an EC2 security
group](https://github.com/kubernetes/ingress-nginx/issues/10302#issuecomment-1686282013)
with the network load balancer. This introduces a challenge when wanting to use
a WAF or other security group-based features.

However, it is now recommended to use the [AWS Load Balancer
Controller](https://kubernetes-sigs.github.io/aws-load-balancer-controller/latest/), a separate
Kubernetes controller that provisions AWS load balancers for Kubernetes services
and ingress resources. This controller is the successor to the AWS ALB Ingress
Controller and is now the recommended way to manage AWS load balancers in
Kubernetes.

# Prerequisites

Add the following environment variables to your shell:

```sh
export AWS_PROFILE=saguaro-cluster
export KUBECONFIG=$PWD/.kube/config
PATH_add bin
```

Install lastest `eksctl` to create the cluster:

```sh
curl -sLO "https://github.com/eksctl-io/eksctl/releases/latest/download/eksctl_Darwin_arm64.tar.gz"
tar -xzf eksctl_Darwin_arm64.tar.gz -C /tmp && rm eksctl_Darwin_arm64.tar.gz
mv /tmp/eksctl bin
```

Check the version:

```sh
$ eksctl version
0.207.0
```

Install kubectl:

```sh
export KUBECTL_VERSION=1.31.8
curl -sLO "https://dl.k8s.io/release/v$KUBECTL_VERSION/bin/darwin/arm64/kubectl"
chmod +x ./kubectl
mv ./kubectl bin
```

Check the version:

```sh
$ kubectl version --client
Client Version: v1.31.8
Kustomize Version: v5.4.2
```

# Create and configure the EKS cluster

Create a cluster with `eksctl`:

```sh
$ eksctl create cluster -f cluster.yaml
```

Create an IAM OIDC provider:

```sh
$ eksctl utils associate-iam-oidc-provider \
    --region us-east-2 \
    --cluster aws-lb-cluster \
    --approve
```

### Install the AWS Load Balancer Controller

Create a policy for the AWS Load Balancer Controller:

```sh
$ curl -o iam-policy.json https://raw.githubusercontent.com/kubernetes-sigs/aws-load-balancer-controller/v2.13.0/docs/install/iam_policy.json
$ aws iam create-policy \
    --policy-name AWSLoadBalancerControllerIAMPolicy \
    --policy-document file://iam-policy.json
$ eksctl create iamserviceaccount \
    --cluster=aws-lb-cluster \
    --namespace=kube-system \
    --name=aws-load-balancer-controller \
    --attach-policy-arn=arn:aws:iam::472354598015:policy/AWSLoadBalancerControllerIAMPolicy \
    --override-existing-serviceaccounts \
    --region us-east-2 \
    --approve
```

Add the controller to the cluster:

```sh
$ helm repo add eks https://aws.github.io/eks-charts
$ helm install aws-load-balancer-controller eks/aws-load-balancer-controller \
    -n kube-system \
    --set clusterName=aws-lb-cluster \
    --set serviceAccount.create=false \
    --set serviceAccount.name=aws-load-balancer-controller
```

# Scenarios

## 1. Application Load Balancer (ALB) with combined Ingress and ACM certificates

This scenarios follows the [EchoServer
example](https://kubernetes-sigs.github.io/aws-load-balancer-controller/latest/examples/echo_server/)
from the AWS Load Balancer Controller, but extends it to support two hosts
(echoserver1a and echoserver1b) via host-based routing and ACM TLS certificates.

| Description                   | Value                            |
| ----------------------------- | -------------------------------- |
| Load balancer managed by      | AWS Load Balancer Controller     |
| Load balancer type            | Application Load Balancer (ALB)  |
| TLS termination               | Application Load Balancer (ALB)  |
| TLS certificates              | AWS Certificate Manager (ACM)    |

Prerequisites:
* Create a wildcard certificate in ACM for the domain `*.saguaro.caktustest.net`
  and update the annotation in the `echoserver-ingress.yaml` file with the ARN
  of the certificate.

### Create resources

Create the echoserver resources:

```sh
kubectl create ns echoserver1
kubectl apply -f 01-alb-ingress-acm/echoserver1a.yaml
kubectl apply -f 01-alb-ingress-acm/echoserver1b.yaml
# The Ingress creates the ALB in AWS
kubectl apply -f 01-alb-ingress-acm/echoserver-ingress.yaml
```

Update DNS entries to point to the ALB:

```sh
# Get the ALB DNS name
kubectl -n echoserver1 get ing -o jsonpath='{.items[].status.loadBalancer.ingress[].hostname}'
# Update DNS entries in Route53 in the AWS console
```

### Validate resources

Valid certificate:

```sh
curl -v https://echoserver1a.saguaro.caktustest.net/ 2>&1 | grep -i Certificate
* TLSv1.2 (IN), TLS handshake, Certificate (11):
* Server certificate:
*  SSL certificate verify ok.
```

HTTP redirect to HTTPS:

```sh
curl -sL http://echoserver1a.saguaro.caktustest.net/ | grep -i Hostname
Hostname: echoserver1a-55d9576c47-vvk4d
```

## Deploy the echoserver resources

```sh
$ kubectl create ns echoserver
$ kubectl apply -f echoserver1.yaml
$ kubectl apply -f echoserver2.yaml
$ kubectl apply -f echoserver-ingress.yaml
```

```sh
curl -v https://echoserver2.saguaro.caktustest.net/ 2>&1 | grep -i Certificate
* TLSv1.2 (IN), TLS handshake, Certificate (11):
* Server certificate:
*  SSL certificate verify ok.
```

## External ALB

```sh
aws elbv2 create-load-balancer \
    --name my-load-balancer \
    --type network \
    --subnets subnet-0e3f5cac72EXAMPLE
```


## Scenarios

### 03 IngressGroup

```sh
kubectl apply -f 03-alb-ingressgroup-acm/echoserver1.yaml
curl -v https://echoserver1.saguaro.caktustest.net/ 2>&1 | grep -i Certificate
```

### 04 TargetGroupBinding

```sh
kubectl apply -f 04-alb-targetgroupbinding/echoverver4.yaml
curl -v https://echoserver4.saguaro.caktustest.net/ 2>&1 | grep -i Certificate
```

## Delete the cluster

```sh
$ eksctl delete cluster -f cluster.yaml
```
