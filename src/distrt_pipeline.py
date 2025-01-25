from kfp import dsl
from kfp.dsl import component

# =========================================================
# Preflight Check Component
# =========================================================
@component(
    base_image="python:3.11-slim",
    packages_to_install=["ray[default]==2.40.0", "mlflow", "requests"]
)
def preflight_checks() -> str:
    """
    Verifies connectivity to Ray cluster and MLflow before proceeding.
    """
    import ray
    import mlflow
    import requests

    # Addresses for Ray and MLflow
    RAY_CLUSTER_ADDRESS = "ray://raycluster-kuberay-head-svc.raycluster.svc:10001"
    MLFLOW_ADDRESS = 'http://mlflow-tracking.mlflow.svc'

    # ---------------------------------------------------------
    # Verify Ray cluster connectivity
    # ---------------------------------------------------------
    try:
        ray.init(address=RAY_CLUSTER_ADDRESS, log_to_driver=False)
        if not ray.is_initialized():
            raise ConnectionError("Could not connect to Ray cluster")
        print("Successfully connected to Ray cluster")
    except Exception as e:
        raise RuntimeError(f"Failed to connect to Ray: {e}")
    finally:
        # Always shutdown Ray after the check
        ray.shutdown()

    # ---------------------------------------------------------
    # Verify MLflow connectivity
    # ---------------------------------------------------------
    try:
        response = requests.get(MLFLOW_ADDRESS)
        if response.status_code != 200:
            raise ConnectionError("MLflow server is not reachable")
        print("Successfully connected to MLflow server")
    except Exception as e:
        raise RuntimeError(f"Failed to connect to MLflow: {e}")

    return "Connectivity verified"

# =========================================================
# Distributed Red-Teaming Component
# =========================================================
@component(
    base_image="python:3.11-slim",
    packages_to_install=["ray[default]==2.40.0", "mlflow"]
)
def run_distrt() -> str:
    """
    Initializes Ray, creates custom_generator.py, and submits Ray tasks inside the Kubeflow step.
    """
    import os
    import ray
    import mlflow
    import sys
    from datetime import datetime
    import json

    # ---------------------------------------------------------
    # Prepare working directory
    # ---------------------------------------------------------
    working_directory = "/tmp/ray_workdir"
    os.makedirs(working_directory, exist_ok=True)

    # ---------------------------------------------------------
    # custom_generator.py code for model inference
    # ---------------------------------------------------------
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

    # Write the code to a local file in the container
    generator_file_path = os.path.join(working_directory, "custom_generator.py")
    with open(generator_file_path, "w") as f:
        f.write(custom_generator_code)

    # ---------------------------------------------------------
    # Environment variables for Ray / MLflow
    # ---------------------------------------------------------
    RAY_CLUSTER_ADDRESS = "ray://raycluster-kuberay-head-svc.raycluster.svc:10001"
    MLFLOW_ADDRESS = 'http://mlflow-tracking.mlflow.svc'
    os.environ['MLFLOW_TRACKING_URI'] = MLFLOW_ADDRESS
    os.environ["RAY_CHDIR_TO_TRIAL_DIR"] = "0"

    # ---------------------------------------------------------
    # Initialize Ray cluster connection
    # ---------------------------------------------------------
    ray.shutdown()  # Ensure any previous Ray session is closed
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

    # ---------------------------------------------------------
    # Helper function to combine JSONL from multiple files
    # ---------------------------------------------------------
    def combine_jsonl_from_dir(directory, output_file):
        # Gather all JSONL files
        jsonl_files = [f for f in os.listdir(directory) if f.endswith("report.jsonl")]
        jsonl_files = [os.path.join(directory, f) for f in jsonl_files]
        if not jsonl_files:
            print("No JSONL files found in the directory.")
            return

        # Combine them into one file
        with open(output_file, "w") as outfile:
            for file in jsonl_files:
                with open(file, "r") as infile:
                    for line in infile:
                        line = line.strip()  # Remove extra whitespace
                        if not line:  # Skip empty lines
                            continue
                        try:
                            json.loads(line)  # Validate JSON
                            outfile.write(line + "\n")  # Write valid JSON lines
                        except json.JSONDecodeError as e:
                            print(f"Skipping malformed JSON in {file}: {e} → {line}")
        print(f"Combined {len(jsonl_files)} JSONL files into {output_file}")

    # ---------------------------------------------------------
    # Define Ray tasks within this step
    # ---------------------------------------------------------

    @ray.remote
    def run_probe(probe_name, mlflow_runid):
        """
        Runs a single Garak probe and logs artifacts to MLflow.
        """
        import garak.cli
        garak_runs_dir = '/home/ray/.local/share/garak/garak_runs/'

        # Construct the CLI command for Garak
        cli_command = f'--parallel_requests 1 --model_type function --model_name generate_response --probes {probe_name}'
        garak.cli.main(cli_command.split())

        # Log the artifacts from Garak to the same MLflow run
        with mlflow.start_run(run_id=mlflow_runid):
            mlflow.log_artifacts(garak_runs_dir)

    @ray.remote
    def run_red_teaming(probes_list, mlflow_runid):
        """
        Runs multiple Garak probes using Ray, combines logs, and generates a final report.
        """
        from garak.command import write_report_digest

        # Dispatch each probe in parallel
        futures = [run_probe.remote(probe_name, mlflow_runid) for probe_name in probes_list]

        # Wait for all to complete
        ray.get(futures)

        # Download artifacts so we can combine logs
        mlflow.artifacts.download_artifacts(run_id=mlflow_runid, dst_path='./combined_logs')

        # Combine JSONL logs into a single file
        combine_jsonl_from_dir('./combined_logs', 'combined_logs.jsonl')

        # Generate a consolidated HTML report
        write_report_digest('combined_logs.jsonl', './final_report.html')
        print(os.listdir())
        print("HTML contents written to final_report.html")

        # Log the final HTML report to MLflow
        with mlflow.start_run(run_id=mlflow_runid):
            mlflow.log_artifact('./final_report.html')

    # ---------------------------------------------------------
    # Start MLflow experiment and run distributed tasks
    # ---------------------------------------------------------
    mlflow.set_experiment("garak_runs")
    print("MLflow Debugging Information")
    print(f"Tracking URI: {mlflow.get_tracking_uri()}")

    # Create a new MLflow run
    with mlflow.start_run(run_name=datetime.now().strftime("%Y-%m-%d_%H-%M-%S")) as run:
        print(f"MLflow Run Started: {run.info.run_id}")
        mlflow_runid = run.info.run_id

        # List of probes to run in parallel via Ray
        probes_list = [
            'grandma.Substances',
            'grandma.Slurs',
            'grandma.Win10',
            'lmrc.Bullying',
            'lmrc.Profanity'
        ]

        # Execute red-teaming logic
        ray.get(run_red_teaming.remote(probes_list, mlflow_runid))

    return "All done!"

# =========================================================
# Post-Processing Component
# =========================================================
@component(base_image="python:3.11-slim")
def post_process() -> str:
    """
    Final step that could handle notifications, alerts, or other tasks.
    """
    return "Send an email alert or sth?"

# =========================================================
# Kubeflow Pipeline Definition
# =========================================================
@dsl.pipeline(
    name='madrigal_pipeline',
    description='A pipeline that runs distributed GenAI Red Teaming'
)
def madrigal_pipeline():
    # Step 1: Run preflight checks to ensure connectivity
    verify_task = preflight_checks()

    # Step 2: Run the distributed red-teaming steps
    init_task = run_distrt().after(verify_task)

    # Step 3: Post-processing step
    post_process().after(init_task)

# =========================================================
# Main Entrypoint for Pipeline Compilation
# =========================================================
if __name__ == "__main__":
    from kfp.compiler import Compiler
    Compiler().compile(madrigal_pipeline, 'madrigal_pipeline.yaml')
