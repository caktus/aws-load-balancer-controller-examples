import troposphere.ec2 as ec2
import troposphere.elasticloadbalancingv2 as elb
from troposphere import (
    GetAtt,
    Join,
    Output,
    Parameter,
    Ref,
    Template,
)


def main():
    template = Template()
    template.set_version("2010-09-09")
    template.set_description("AWS CloudFormation Template: LB for EKS Cluster")

    vpc_id = template.add_parameter(
        Parameter("VpcId", Type="String", Default="vpc-087ccad6480af2d0a")
    )
    subnet_a = template.add_parameter(
        Parameter("SubnetA", Type="String", Default="subnet-01e2432f0a0b86dfc")
    )
    subnet_b = template.add_parameter(
        Parameter("SubnetB", Type="String", Default="subnet-01bf7181d64240211")
    )
    scheme = template.add_parameter(
        Parameter(
            "LBScheme",
            Description="The type of load balancer to create",
            Type="String",
            Default="internet-facing",
            AllowedValues=["internet-facing", "internal"],
        ),
    )

    frontend_sg = ec2.SecurityGroup(
        "FrontEndSecurityGroup",
        GroupDescription="Inbound security group for the cluster",
        SecurityGroupIngress=[
            ec2.SecurityGroupRule(
                IpProtocol="tcp",
                FromPort="80",
                ToPort="80",
                CidrIp="0.0.0.0/0",
            ),
            ec2.SecurityGroupRule(
                IpProtocol="tcp",
                FromPort="443",
                ToPort="443",
                CidrIp="0.0.0.0/0",
            ),
        ],
        VpcId=Ref(vpc_id),
        template=template,
    )

    # Add the application ELB
    load_balancer = elb.LoadBalancer(
        "ClusterLB",
        Name=Join("-", [Ref("AWS::StackName"), "cluster-lb"]),
        Scheme=Ref(scheme),
        Subnets=[Ref(subnet_a), Ref(subnet_b)],
        SecurityGroups=[GetAtt(frontend_sg, "GroupId")],
        template=template,
    )

    target_group = elb.TargetGroup(
        "TargetGroupHTTPS",
        Name="target-group-https",
        Port="443",
        Protocol="HTTP",
        VpcId=Ref(vpc_id),
        template=template,
    )

    listener = elb.Listener(
        "ListenerHTTPS",
        Port="443",
        Protocol="HTTP",
        LoadBalancerArn=Ref(load_balancer),
        DefaultActions=[elb.Action(Type="forward", TargetGroupArn=Ref(target_group))],
        template=template,
    )

    # template.add_resource(
    #     elb.ListenerRule(
    #         "ListenerRuleApi",
    #         ListenerArn=Ref(Listener),
    #         Conditions=[elb.Condition(Fild="path-pattern", Values=["/api/*"])],
    #         Actions=[
    #             elb.ListenerRuleAction(
    #                 Type="forward", TargetGroupArn=Ref(TargetGroupApi)
    #             )
    #         ],
    #         Priority="1",
    #     )
    # )

    # template.add_output(
    #     Output(
    #         "URL",
    #         Description="URL of the sample website",
    #         Value=Join("", ["http://", GetAtt(ApplicationElasticLB, "DNSName")]),
    #     )
    # )

    print(template.to_yaml())


if __name__ == "__main__":
    main()
