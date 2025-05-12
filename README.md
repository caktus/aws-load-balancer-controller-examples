# Migrating to the AWS Load Balancer Controller

Caktus uses the [NGINX Ingress
Controller](https://github.com/kubernetes/ingress-nginx) to manage ingress
traffic in our Kubernetes clusters. In AWS, we use a [Network load balancer
(NLB)](https://docs.aws.amazon.com/elasticloadbalancing/latest/network/introduction.html)
to expose the controller behind a Service of ``Type=LoadBalancer``. By default,
this uses the legacy "in-tree" (within ingress-nginx itself) service load balancer for
AWS NLB. However, it is now recommended to use the [AWS Load Balancer
Controller](https://kubernetes-sigs.github.io/aws-load-balancer-controller/latest/), a separate
Kubernetes controller that provisions AWS load balancers for Kubernetes services
and ingress resources. This controller is the successor to the AWS ALB Ingress
Controller and is now the recommended way to manage AWS load balancers in
Kubernetes.

## Prerequisites

Add the following environment variables to your shell:

```sh
export AWS_PROFILE=saguaro-cluster
export KUBECONFIG=$PWD/.kube/config
PATH_add bin
```

Install lastest `eksctl` to create the cluster:

```sh
$ curl -sLO "https://github.com/eksctl-io/eksctl/releases/latest/download/eksctl_Darwin_arm64.tar.gz"
$ tar -xzf eksctl_Darwin_arm64.tar.gz -C /tmp && rm eksctl_Darwin_arm64.tar.gz
$ mv /tmp/eksctl bin
$ eksctl version
0.207.0
```

Install kubectl:

```sh
$ export KUBECTL_VERSION=1.31.8
$ curl -sLO "https://dl.k8s.io/release/v$KUBECTL_VERSION/bin/darwin/arm64/kubectl"
$ chmod +x ./kubectl
$ mv ./kubectl bin
$ kubectl version --client
Client Version: v1.31.8
Kustomize Version: v5.4.2
```


## Create an EKS cluster

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


## Install the AWS Load Balancer Controller

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

Verify the installation:

```sh
$ kubectl get deployment -n kube-system aws-load-balancer-controller
```

## Install cert-manager

Install cert-manager with Helm:

```sh
$ helm repo add jetstack https://charts.jetstack.io --force-update
$ helm install \
  cert-manager jetstack/cert-manager \
  --namespace cert-manager \
  --create-namespace \
  --version v1.17.2 \
  --set crds.enabled=true
```

Install the cert-manager issuer:

```sh
$ kubectl apply -f cert-manager-issuer.yaml
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


## Delete the cluster

```sh
$ eksctl delete cluster -f cluster.yaml
```
