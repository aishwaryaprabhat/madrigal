kubectl -n argocd get secret argocd-initial-admin-secret -o jsonpath="{.data.password}" | base64 -d && echo
kubectl -n argowf exec -it $(kubectl get pods -n argowf | grep argo-workflows-server | awk '{print $1}') -- argo auth token

# Kill prior services running on the ports
for port in 8080 9001 9000 5000 2746 8081 8082 10001 8265; do
  fuser -k $port/tcp
done

kubectl -n argocd port-forward svc/argocd-server 8080:80 &
kubectl -n mlflow port-forward svc/mlflow-tracking 5000:80 &
kubectl -n raycluster port-forward svc/raycluster-kuberay-head-svc 10001 &
kubectl -n raycluster port-forward svc/raycluster-kuberay-head-svc 8265 &
kubectl -n kubeflow port-forward svc/ml-pipeline-ui 8001:80 &
kubectl -n kubeflow port-forward svc/ml-pipeline 8888 &
kubectl -n argowf port-forward svc/argowf-argo-workflows-server 2746 &

conda activate rayvenv

cd goku/goku/dream && jupyter lab --allow-root

# psql -h localhost -p 5432 -U postgresw
# kubectl -n <ns> delete <resource> --all --grace-period=0 --force
# fuser -k 5000/tcp && kubectl -n mlflow port-forward svc/mlflow 5000 &
curl https://localhost:2746/api/v1/workflows/argo -H "Authorization: $ARGO_TOKEN"
# 200 OK
