import torch
from transformers import AutoModelForCausalLM, AutoTokenizer
import mlflow

def download_mlflow_model(experiment_name='HuggingFaceTB', dest_path='SmolLM2-135M-Instruct'):
    
    client = mlflow.tracking.MlflowClient()
    experiments = client.search_experiments()
    if experiments:
        print("📋 Available Experiments:")
        for exp in experiments:
            print(f" - {exp.name} (ID: {exp.experiment_id})")
    else:
        print("⚠️ No experiments found in MLflow.")
    experiment = client.get_experiment_by_name(experiment_name)
    runs = client.search_runs(experiment.experiment_id, order_by=["start_time desc"])
    if not runs:
        raise ValueError("No runs found for experiment")
    
    latest_run_id = runs[0].info.run_id
    print(f"🔗 Latest Run ID: {latest_run_id}")
    # List artifacts in this run
    artifacts = client.list_artifacts(latest_run_id)
    for artifact in artifacts:
        print(f"📂 Artifact: {artifact.path}")
    MODEL_DOWNLOAD_PATH = mlflow.artifacts.download_artifacts(run_id=latest_run_id, dst_path=dest_path)
    print(f"✅ Model downloaded to: {MODEL_DOWNLOAD_PATH}")

    return MODEL_DOWNLOAD_PATH


model_loaded = False
model = None
tokenizer = None

def generate_response(prompt):
    global model_loaded, model, tokenizer
    
    if not model_loaded:
        experiment_name='HuggingFaceTB'
        dest_path='SmolLM2-135M-Instruct'
        
        model_download_path = download_mlflow_model(experiment_name, dest_path)
        model = AutoModelForCausalLM.from_pretrained(model_download_path)
        tokenizer = AutoTokenizer.from_pretrained(model_download_path)
        model_loaded = True

    inputs = tokenizer(prompt, return_tensors="pt")
    with torch.no_grad():
        output_tokens = model.generate(**inputs, max_length=100)
    return [tokenizer.decode(output_tokens[0], skip_special_tokens=True)]

