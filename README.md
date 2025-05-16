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
  - [2. Application Load Balancer (ALB) with IngressGroup and ACM certificates](#2-application-load-balancer-alb-with-ingressgroup-and-acm-certificates)
    - [Create resources](#create-resources-1)
    - [Validate resources](#validate-resources-1)
  - [3. Application Load Balancer (ALB) with TargetGroupBinding (IN PROGRESS)](#3-application-load-balancer-alb-with-targetgroupbinding-in-progress)
    - [Create resources](#create-resources-2)
    - [Validate resources](#validate-resources-2)
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

I had trouble finding complete examples (with Kubernetes manifests) that
demonstrated how to use the controller to implement common use cases at Caktus,
such as using multiple TLS certificates, using the same LB for multiple Ingress
resources, managing HTTP redirects, and handling both www and apex domains, so I
decided to create this repository to document our findings and provide examples.

# Prerequisites

Add the following environment variables to your shell:

```sh
export AWS_PROFILE=saguaro-cluster
export KUBECONFIG=$PWD/.kube/config
export AWS_REGION=us-east-2
export AWS_DEFAULT_REGION=$AWS_REGION
PATH_add bin
layout python python3.12
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

## 2. Application Load Balancer (ALB) with IngressGroup and ACM certificates

Following the previous example, this scenario uses:

* The
  [group.name](https://kubernetes-sigs.github.io/aws-load-balancer-controller/latest/guide/ingress/ingress_class/#specgroup)
  annotation so that the Ingress resources are grouped together in the same ALB.
  This is useful when you want to share the same ALB for multiple Ingress
  resources and avoid creating multiple ALBs for each Ingress resource.
* Individual ACM certificates for each Ingress resource, so we can support both
  the ``www`` and apex domains.

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
* Create a certificate in ACM for the domain
  `echoserver2b.saguaro.caktustest.net` and
  `www.echoserver2b.saguaro.caktustest.net` in AWS ACM

### Create resources

Create the echoserver resources:

```sh
kubectl create ns echoserver2
# The first Ingress creates the ALB in AWS
kubectl apply -f 02-alb-ingressgroup-acm/echoserver2a.yaml
kubectl apply -f 02-alb-ingressgroup-acm/echoserver2b.yaml
```

Update DNS entries to point to the ALB. Both Ingress resources will share the
same ALB:

```sh
# Get the ALB DNS name
kubectl -n echoserver2 get ing
# Update DNS entries in Route53 in the AWS console
```

### Validate resources

Valid certificate:

```sh
curl -v https://www.echoserver2b.saguaro.caktustest.net/ 2>&1 | grep -i Certificate
* TLSv1.2 (IN), TLS handshake, Certificate (11):
* Server certificate:
*  SSL certificate verify ok.
```

HTTP redirect to HTTPS:

```sh
curl -sL http://www.echoserver2b.saguaro.caktustest.net/ | grep -i Hostname
Hostname: echoserver2b-6f64f579cc-f2spf
```

## 3. Application Load Balancer (ALB) with TargetGroupBinding (IN PROGRESS)

This scenario provisions the ALB with CloudFormation outside of the Kubernetes
cluster and uses the `TargetGroupBinding` resource to bind the Kubernetes
``Service`` to ALB Target Groups. This allows you to manage the ALB lifecycle
independently of the Kubernetes cluster, so cluster resources can be recreated
or deleted without affecting the ALB and you can gurantee the DNS name of the
ALB remains constant, which may be important for production workloads.

* Create the ALB with Cloudformation, not using the AWS Load Balancer
  Controller.
* Use `TargetGroupBinding` resources to bind the Service to an existing ALB.

| Description                   | Value                            |
| ----------------------------- | -------------------------------- |
| Load balancer managed by      | AWS CloudFormation               |
| Load balancer type            | Application Load Balancer (ALB)  |
| TLS termination               | Application Load Balancer (ALB)  |
| TLS certificates              | AWS Certificate Manager (ACM)    |

### Create resources

Install Python requirements, generate the CloudFormation template, and create
the ALB:

```sh
export ENV=staging
# Install Python requirements
pip install -r 03-alb-targetgroupbinding/requirements.txt
# Generate the CloudFormation template to create the ALB ourselves
python 03-alb-targetgroupbinding/alb.py > 03-alb-targetgroupbinding/alb.yaml
# Create the ALB with CloudFormation
aws cloudformation create-stack \
    --region $REGION \
    --stack-name $AWS_REGION \
    --template-body file://03-alb-targetgroupbinding/alb.yaml
# Wait for the stack to be created
aws cloudformation wait stack-create-complete \
    --region $AWS_REGION \
    --stack-name $ENV
# Get the ALB Arn
export LB_VPC=$(aws elbv2 describe-load-balancers \
    --names=$ENV-cluster-lb \
    --region $AWS_REGION \
    --query="LoadBalancers[0].VpcId" \
    --output text
)
```

In order to create the `TargetGroupBinding` resource, we need to create the
Target Group in AWS first. We'll use the `ip` target type here, so that we don't
need to manage or look up `NodePorts` for external access.

```sh
# Create a Target Group for the echoserver3a Service
export TARGET_GROUP_ARN_ECHOSERVER3A=$(aws elbv2 create-target-group \
    --name echoserver3a \
    --protocol HTTP \
    --target-type ip \
    --port 8080 \
    --region $AWS_REGION \
    --vpc-id $LB_VPC \
    --query "TargetGroups[0].TargetGroupArn" \
    --output text
)
# And one for the echoserver3b Service, which uses port 80
# to illustrate
export TARGET_GROUP_ARN_ECHOSERVER3B=$(aws elbv2 create-target-group \
    --name echoserver3b \
    --protocol HTTP \
    --target-type ip \
    --port 80 \
    --region $AWS_REGION \
    --vpc-id $LB_VPC \
    --query "TargetGroups[0].TargetGroupArn" \
    --output text
)
```

Next we'll create the `TargetGroupBinding` (and `Service`) resources for
echoserver3. These resources bind the Kubernetes `Service` to the Target Groups
in AWS created above. The `TargetGroupBinding` resource is used to register the
Kubernetes Pods with the Target Group, so that traffic can be routed to them.

We'll also create `ClusterIP` type Services for the echoserver3. The `Service`
is still used by the AWS Load Balancer Controller to discover which Pods to
register with the Target Group, based on label selectors.

Apply the manifests:

```sh
kubectl create ns echoserver3
# Now we can create the echoserver3a Service and TargetGroupBinding resource
kubectl apply -f 03-alb-targetgroupbinding/echoserver3a.yaml
# And the echoserver3b Service and TargetGroupBinding resource
kubectl apply -f 03-alb-targetgroupbinding/echoserver3b.yaml
```

But we're not done! A Rule is needed to route traffic to the Target Groups.
We'll use the AWS CLI to create the Rule for the ALB. The Rule will route
traffic to the Target Groups based on the `Host` header and attach it to the ALB
listeners created in the CloudFormation template above.


```sh
aws elbv2 create-rule \
    --listener-arn arn:aws:elasticloadbalancing:us-west-2:123456789012:listener/app/my-load-balancer/50dc6c495c0c9188/f2f7dc8efc522ab2 \
    --priority 5 \
    --conditions file://conditions-pattern.json
    --actions Type=forward,TargetGroupArn=arn:aws:elasticloadbalancing:us-west-2:123456789012:targetgroup/my-targets/73e2d6bc24d8a067
```




```sh
curl -v https://echoserver3a.saguaro.caktustest.net/ 2>&1 | grep -i Certificate
* (304) (IN), TLS handshake, Certificate (11):
* Server certificate:
*  SSL certificate verify ok.
```



### Validate resources




# Delete the cluster

When you are done testing, you can delete the cluster with `eksctl`:

```sh
$ eksctl delete cluster -f cluster.yaml
```
