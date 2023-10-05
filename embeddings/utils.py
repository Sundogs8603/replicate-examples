import os
import subprocess
import random
import time
import typing as tp
import asyncio


def get_env_var_or_default(var_name, default_value):
    """
    Attempts to load a global variable from an environment variable.

    Args:
    - var_name (str): Name of the global variable.
    - default_value: The default value to use if the environment variable doesn't exist or its length is 0.

    Returns:
    - value: The value from the environment variable or the default value.
    """
    env_value = os.environ.get(var_name, "")

    # Check if the environment variable exists and is not empty
    if len(env_value) > 0:
        return env_value
    else:
        return default_value


class Logger:
    def __init__(self, marker: str = "predict-timings"):
        self.marker = marker + "%s" % random.randint(0, 1000000)
        self.start = time.time()
        self.last = self.start

    def log(self, *args):
        current_time = time.time()
        elapsed_since_start = current_time - self.start
        elapsed_since_last_log = current_time - self.last

        message = " ".join(str(arg) for arg in args)
        timings = f"{elapsed_since_start:.2f}s since start, {elapsed_since_last_log:.2f}s since last log"

        print(f"{self.marker}: {message} - {timings}")
        self.last = current_time

    def info(self, *args):
        self.log(*args)

def download_file(file, local_filename):
    print(f"Downloading {file} to {local_filename}")
    if os.path.exists(local_filename):
        os.remove(local_filename)
    if "/" in local_filename:
        if not os.path.exists(os.path.dirname(local_filename)):
            os.makedirs(os.path.dirname(local_filename), exist_ok=True)

    command = ["pget", file, local_filename]
    subprocess.check_call(command, close_fds=True)
    return


def check_files_exist(remote_files, local_path):
    # Get the list of local file names
    local_files = os.listdir(local_path)

    # Check if each remote file exists in the local directory
    missing_files = [file for file in remote_files if file not in local_files]

    return missing_files


async def download_file_with_pget(remote_path, dest_path):
    # Create the subprocess
    print("Downloading ", remote_path)
    if remote_path.endswith("json"):
        info = "%{filename_effective} took %{time_total}s (%{speed_download} bytes/sec)\n"
        args = ["curl", "-w", info, "-sLo", dest_path, remote_path]
    else:
        args = ["pget", remote_path, dest_path]
    process = await asyncio.create_subprocess_exec(
        *args,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        close_fds=True,
    )

    # Wait for the subprocess to finish
    stdout, stderr = await process.communicate()

    # Print what the subprocess output (if any)
    if stdout:
        print(f"[stdout]\n{stdout.decode()}")
    if stderr:
        print(f"[stderr]\n{stderr.decode()}")


async def download_files_with_pget(remote_path, path, files):
    await asyncio.gather(
        *(
            download_file_with_pget(f"{remote_path}/{file}", f"{path}/{file}")
            for file in files
        )
    )

    # # Run the bash script for each missing file
    # process = subprocess.Popen(["./src/download-with-pget.sh", remote_path, path, *files])
    # process.wait()

def list_remote_filenames(remote_path):
    """
    Given a remote bucket path, return a list of all files in the bucket.
    
    Example:
    
    ```
    >>> list_remote_filenames("gs://my-bucket/username/roberta-base")
    ["config.json", "pytorch_model.bin", "tokenizer.json", "vocab.json"]
    
    >>> list_remote_filenames("https://storage.googleapis.com/my-bucket/username/roberta-base")
    ["config.json", "pytorch_model.bin", "tokenizer.json", "vocab.json"]
    ```
    """
    try:
        from google.cloud import storage
    except:
        raise ImportError(
            "google-cloud-storage is not installed. Can't infer remote filenames without it. "
            "Please either install it or pass in remote_filenames."
        )
    bucket_name, *prefixes = remote_path.replace("https://storage.googleapis.com/", "").replace("gs://", "").split("/")
    prefix = "/".join(prefixes)
    print("bucket name", bucket_name)
    print("prefix", prefix)
    client = storage.Client()
    bucket = client.bucket(bucket_name)
    blobs = bucket.list_blobs(prefix=prefix)
    remote_filenames = [blob.name[len(prefix) + 1:] for blob in blobs]
    print(f"Found {len(remote_filenames)} files in {remote_path}:\n{remote_filenames}")
    return remote_filenames


def maybe_download_with_pget(
    path,
    remote_path: tp.Optional[str] = None,
    remote_filenames: tp.Optional[tp.List[str]] = None,
    logger: tp.Optional[Logger] = None,
):
    """
    Downloads files from remote_path to path if they are not present in path. File paths are constructed
    by concatenating remote_path and remote_filenames. If remote_path is None, files are not downloaded.

    Args:
        path (str): Path to the directory where files should be downloaded
        remote_path (str): Path to the directory where files should be downloaded from
        remote_filenames (List[str]): List of file names to download
        logger (Logger): Logger object to log progress

    Returns:
        path (str): Path to the directory where files were downloaded

    Example:

        maybe_download_with_pget(
            path="models/roberta-base",
            remote_path="gs://my-bucket/username/roberta-base",
            remote_filenames=["config.json", "pytorch_model.bin", "tokenizer.json", "vocab.json"],
            logger=logger
        )
    """

    if remote_path:
        remote_path = remote_path.rstrip("/")
        remote_path = remote_path.replace("gs://", "https://storage.googleapis.com/")

        if remote_filenames is None:
            remote_filenames = list_remote_filenames(remote_path)

        if not os.path.exists(path):
            os.makedirs(path, exist_ok=True)
            missing_files = remote_filenames
        else:
            local_files = os.listdir(path)
            # TODO - can delete this and the fn
            # missing_files = check_files_exist(remote_filenames, path)
            missing_files = [file for file in remote_filenames if file not in local_files]
        
        # Make all parent dirs for missing files if they don't exist
        for file in missing_files:
            if "/" in file:
                if not os.path.exists(os.path.dirname(os.path.join(path, file))):
                    os.makedirs(os.path.dirname(os.path.join(path, file)), exist_ok=True)

        if len(missing_files) > 0:
            print("Downloading weights...")
            st = time.time()
            if logger:
                logger.info(f"Downloading {missing_files} from {remote_path} to {path}")
            asyncio.run(download_files_with_pget(remote_path, path, missing_files))
            if logger:
                logger.info(f"Finished download")
            print(f"Finished download in {time.time() - st:.2f}s")

    return path


# if __name__ == '__main__':
    # from huggingface_hub import model_info

    # huggingface_model_id = "nateraw/rare-puppers"
    # # huggingface_model_id ="BAAI/bge-small-en"
    # sha = model_info(huggingface_model_id).sha
    # remote_path = f"gs://bucket-name/{huggingface_model_id}/{sha}"
    # remote_filenames = list_remote_filenames(remote_path)

    # remote_path = f"gs://bucket-name/{huggingface_model_id}/{sha}"
    # remote_filenames = list_remote_filenames(remote_path)
    # maybe_download_with_pget(huggingface_model_id, remote_path)
