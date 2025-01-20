sudo snap install microk8s --classic --channel=1.32
mkdir -p ~/.kube
microk8s status --wait-ready
microk8s enable hostpath-storage
alias kubectl='microk8s kubectl'
microk8s add-node
