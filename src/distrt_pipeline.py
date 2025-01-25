from kfp import dsl
from kfp.dsl import component

@component(base_image="python:3.11-slim", packages_to_install=["ray[default]==2.40.0", "mlflow"])
def run_distrt() -> str:
    """Initializes Ray, creates custom_generator.py, and submits Ray tasks inside the Kubeflow step."""
    import os
    import ray
    import mlflow
    import sys
    from datetime import datetime

    working_directory = "/tmp/ray_workdir"
    os.makedirs(working_directory, exist_ok=True)
    
    # Define the content of custom_generator.py
    custom_generator_code = """
import torch
from transformers import AutoModelForCausalLM, AutoTokenizer
import mlflow

def download_mlflow_model(experiment_name='HuggingFaceTB', dest_path='SmolLM2-135M-Instruct'):
    client = mlflow.tracking.MlflowClient()
    experiment = client.get_experiment_by_name(experiment_name)
    runs = client.search_runs(experiment.experiment_id, order_by=["start_time desc"])
    if not runs:
        raise ValueError("No runs found for experiment")
    latest_run_id = runs[0].info.run_id
    MODEL_DOWNLOAD_PATH = mlflow.artifacts.download_artifacts(run_id=latest_run_id, dst_path=dest_path)
    return MODEL_DOWNLOAD_PATH

model_loaded = False
model = None
tokenizer = None

def generate_response(prompt):
    global model_loaded, model, tokenizer
    if not model_loaded:
        model_download_path = download_mlflow_model('HuggingFaceTB', 'SmolLM2-135M-Instruct')
        model = AutoModelForCausalLM.from_pretrained(model_download_path)
        tokenizer = AutoTokenizer.from_pretrained(model_download_path)
        model_loaded = True
        print('Model downloaded and available for generating responses!')
    inputs = tokenizer(prompt, return_tensors="pt")
    with torch.no_grad():
        output_tokens = model.generate(**inputs, max_length=100)
    return [tokenizer.decode(output_tokens[0], skip_special_tokens=True)]
    """
    
    generator_file_path = os.path.join(working_directory, "custom_generator.py")
    with open(generator_file_path, "w") as f:
        f.write(custom_generator_code)
 

    RAY_CLUSTER_ADDRESS = "ray://raycluster-kuberay-head-svc.raycluster.svc:10001"
    MLFLOW_ADDRESS = 'http://mlflow-tracking.mlflow.svc'
    os.environ['MLFLOW_TRACKING_URI'] = MLFLOW_ADDRESS
    os.environ["RAY_CHDIR_TO_TRIAL_DIR"] = "0"
    
    ray.shutdown()
    ray.init(
        address=RAY_CLUSTER_ADDRESS,
        log_to_driver=False,
        runtime_env={
            "pip": ["torch", "transformers", "garak", "mlflow"],
            "env_vars": {
                'MLFLOW_TRACKING_URI': MLFLOW_ADDRESS
            },
            "working_dir": working_directory
        }
    )

    def combine_jsonl_from_dir(directory, output_file):
        jsonl_files = [f for f in os.listdir(directory) if f.endswith("report.jsonl")]  # Get all JSONL files
        jsonl_files = [os.path.join(directory, f) for f in jsonl_files]  # Full file paths
        if not jsonl_files:
            print("No JSONL files found in the directory.")
            return
        with open(output_file, "w") as outfile:
            for file in jsonl_files:
                with open(file, "r") as infile:
                    for line in infile:
                        line = line.strip()  # Remove extra whitespace
                        
                        if not line:  # Ignore empty lines
                            continue
                        
                        try:
                            json.loads(line)  # Validate JSON
                            outfile.write(line + "\n")  # Ensure each JSON object is on a separate line
                        except json.JSONDecodeError as e:
                            print(f"Skipping malformed JSON in {file}: {e} → {line}")
        print(f"Combined {len(jsonl_files)} JSONL files into {output_file}")

    
    # Define Ray tasks inside the Kubeflow step
    @ray.remote
    def run_probe(probe_name, mlflow_runid):
        """Runs a single Garak probe and logs artifacts."""
        import garak.cli
        garak_runs_dir = '/home/ray/.local/share/garak/garak_runs/'
        cli_command = f'--parallel_requests 1 --model_type function --model_name generate_response --probes {probe_name}'
        garak.cli.main(cli_command.split())
        with mlflow.start_run(run_id=mlflow_runid):
            mlflow.log_artifacts(garak_runs_dir)

    @ray.remote
    def run_red_teaming(probes_list, mlflow_runid):
        """Runs multiple Garak probes using Ray."""
        from garak.command import write_report_digest
        futures = [run_probe.remote(probe_name, mlflow_runid) for probe_name in probes_list]
        ray.get(futures)
        mlflow.artifacts.download_artifacts(run_id=mlflow_runid, dst_path='./combined_logs')
        combine_jsonl_from_dir('./combined_logs', 'combined_logs.jsonl')
        write_report_digest('combined_logs.jsonl', './final_report.html')
        print(os.listdir())
        print("HTML contents writtten to final_report.html")
        mlflow.log_artifact('./final_report.html')

    
    # Start MLflow experiment and submit Ray tasks
    mlflow.set_experiment("garak_runs")
    print("MLflow Debugging Information")
    print(f"Tracking URI: {mlflow.get_tracking_uri()}")
    with mlflow.start_run(run_name=datetime.now().strftime("%Y-%m-%d_%H-%M-%S")) as run:
        print(f"MLflow Run Started: {run.info.run_id}")
        mlflow_runid = run.info.run_id
        probes_list = ['grandma.Substances', 'grandma.Slurs', 'grandma.Win10', 'lmrc.Bullying', 'lmrc.Profanity']
        ray.get(run_red_teaming.remote(probes_list, mlflow_runid))
    
    return "All done!"

@component(base_image="python:3.11-slim")
def post_process() -> str:
    return "All hail Ray!"

@dsl.pipeline(name='madrigal_pipeline', description='A pipeline that runs distributed GenAI Red Teaming')
def madrigal_pipeline():
    init_task = run_distrt()
    post_process().after(init_task)

if __name__ == "__main__":
    from kfp.compiler import Compiler
    Compiler().compile(madrigal_pipeline, 'madrigal_pipeline.yaml')
