# Installation Guide

This whole setup should work fine on Minikube or any other flavour of Kubernetes. However, setting up all the components and hosting LLMs might require a little more than what your laptop can handle. In my case, I used Digital Ocean droplets to form a microk8s cluster which makes the creation of a multi-node kubernetes cluster with PVs etc. very straightforward.

## 1. Cluster Setup
1. Setup a microk8s cluster using [this script](./k8s/bootstrap/microk8s_setup.sh)
2. Add nodes to the microk8s cluster using the output of the command `microk8s add-node`
3. Setup argocd by running the [argocd installation script](./k8s/bootstrap/argocd_setup.sh). `bash ./k8s/bootstrap/argocd_setup.sh` should get the job done.
4. To view ArgoCD UI, run the following to obtain admin secret and setup port-forwarding
```shell
kubectl -n argocd get secret argocd-initial-admin-secret -o jsonpath="{.data.password}" | base64 -d && echo
kubectl -n argocd port-forward svc/argocd-server 8080:80 &
```

## 2. MinIO Setup
1. Run the command `kubectl apply -f k8s/argocd_apps/minio.yaml` which will install MinIO as an argocd app
2. Navigate to ArgoCD UI, select the MinIO app and click on "Sync">"Synchronize"
3. Observe to ensure that everything gets setup correctly, including the logs of the minio pod
![](assets/screenshots/minio_argocd.png)
4. To navigate to MinIO console, setup port-forwarding using `kubectl -n minio port-forward svc/minio-console 9001`
5. Login using the username "admin" and password "password" (as is set in [config](./k8s/argocd_apps/minio.yaml))
6. You should eventually end up on the MinIO console
![](assets/screenshots/minio.png)

## 3. Postgres Setup
1. To setup the prerequisites, run the [postgres prerequisites script](./k8s/scripts/postgres_prereq.sh). `bash k8s/scripts/postgres_prereq.sh` should get the job done.
2. Run the command `kubectl apply -f k8s/argocd_apps/postgres.yaml`
3. Navigate to ArgoCD UI, select the Postgres app and click on "Sync">"Synchronize"
4. Observe to ensure that everything gets setup correctly, including the logs of the postgres pod
![](assets/screenshots/potgres_argocd.png)
5. For further interactions with postgres (eg: creating mlflow database), we need the psql client. Install it using `sudo apt-get install postgresql-client`.
6. You can run `psql --version` to verify installation

## 4. MLFlow Setup
1. Ensure that MinIO and Postgres are setup as specified in steps 2 and 3 above
2. Navigate to the MinIO console and create a new bucket called "mlflow" ![](assets/screenshots/mlflow_bucket.png)
3. Create a new policy
```json
{
    "Version": "2012-10-17",
    "Statement": [
        {
            "Effect": "Allow",
            "Action": [
                "s3:GetBucketLocation",
                "s3:ListBucket"
            ],
            "Resource": [
                "arn:aws:s3:::mlflow"
            ]
        },
        {
            "Effect": "Allow",
            "Action": [
                "s3:DeleteObject",
                "s3:GetObject",
                "s3:PutObject"
            ],
            "Resource": [
                "arn:aws:s3:::mlflow/*"
            ]
        }
    ]
}
```
![](../docs/assets/screenshots/create_policy_minio.png)
4. On MinIO create a new user and select the policy you just created to associate it with the new user you are creating
![](../docs/assets/screenshots/create_user_minio.png)
5. Next, create a new access key for this user
![](../docs/assets/screenshots/ak1_minio.png)
![](../docs/assets/screenshots/ak2_minio.png)
Record/download this access key as we will need to authenticate MLflow server against the S3 bucket later on.
6. Run the following commands to setup the "mlflow" database in Postgres
```shell
# install psql
sudo apt update
sudo apt install postgresql postgresql-contrib

kubectl -n postgresql port-forward svc/postgres-postgresql 5432 &
psql -h localhost -p 5432 -U postgres
#Enter password "password" when prompted
CREATE DATABASE mlflow;
\q
```
7. Run the command `kubectl apply -f k8s/argocd_apps/mlflow.yaml`
8. Navigate to ArgoCD UI, navigate to the MLFlow app and click on "Details" then "Edit" then "Parameters" tab to replace the placeholder values of the artifactRoot.s3.awsAccessKeyId and artifactRoot.s3.awsSecretAccessKey with the accesskey credentials you created in the MinIO steps above
![](../docs/assets/screenshots/mlflow_creds.png)
9. Next, click on "Sync"
10. Observe to ensure that everything gets setup correctly, including the logs of the mlflow pod
![](assets/screenshots/mlflow_argocd.png)
11. You can use `kubectl -n mlflow port-forward svc/mlflow 5000` to port-forward to the MLFlow server and UI
![](assets/screenshots/mlflow.png)

## 4. Kube-Ray & RayCluster
1. To setup KubeRay Operator, simply run `kubectl apply -f k8s/argocd_apps/kuberay-operator.yaml`
2. Navigate to ArgoCD UI and click on "Sync">"Synchronize"
3. Observe to ensure that everything gets setup correctly
![](assets/screenshots/rayoperator_argocd.png)
4. Next, install a RayCluster by running `kubectl apply -f k8s/argocd_apps/raycluster.yaml`
5. Navigate to ArgoCD UI and click on "Sync">"Synchronize"
6. Observe to ensure that everything gets setup correctly
![](assets/screenshots/raycluster_argocd.png)


## 5. ArgoWorkflows Setup
1. To setup ArgoWF, simply run `kubectl apply -f k8s/argocd_apps/argowf.yaml`
2. Navigate to ArgoCD UI and click on "Sync">"Synchronize"
3. Observe to ensure that everything gets setup correctly
![](assets/screenshots/argowf_argocd.png)
4. Run the following command to obtain admin token required for login in the coming steps
`kubectl -n argowf exec -it $(kubectl get pods -n argowf | grep argo-workflows-server | awk '{print $1}') -- argo auth token`
5. To view the ArgoWF UI, port-forward using `kubectl -n argowf port-forward svc/argowf-argo-workflows-server 2746`
6. To login, stick the Bearer token obtained in and click "Login"
![](assets/screenshots/argowf_login.png)
Voila!
![](assets/screenshots/argowf_landing.png)

