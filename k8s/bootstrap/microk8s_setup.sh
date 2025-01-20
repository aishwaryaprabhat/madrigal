sudo snap install microk8s --classic --channel=1.32
microk8s enable hostpath-storage
alias kubectl='microk8s kubectl'
