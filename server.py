import asyncio
import functools
import http
import json
import os
import signal
import subprocess
import time
import webbrowser

import websockets

# remarkable_addr = 'remarkable'
remarkable_addr = '10.11.99.1'
ssh_key = '~/.ssh/id_rsa'
remarkable_user = 'root'
debug = False


def check(rm_hostname: str):
    try:
        if debug:
            print("before")
        # Command passed as a string because of shell=True
        if ssh_key:
            model = subprocess.run(
                f"ssh -o ConnectTimeout=2 -i {
                    ssh_key} {remarkable_user}@{rm_hostname} cat /proc/device-tree/model",
                check=True,
                shell=True,
                capture_output=True,
            )
        else:
            model = subprocess.run(
                f"ssh -o ConnectTimeout=2 {
                    rm_hostname} cat /proc/device-tree/model",
                check=True,
                shell=True,
                capture_output=True,
            )
        # Decode and return the first 14 bytes as a string
        return model.stdout[:14].decode("utf-8")

    except subprocess.CalledProcessError:
        if debug:
            print(f"Error: Can't connect to reMarkable tablet on hostname: {
                rm_hostname}")
        os._exit(1)


def is_pen(packet) -> bool | None:
    # print(packet)
    # Split the raw packet every 2 characters
    if len(packet) == 16:  # If the packet is complete
        code = int.from_bytes(packet[10:12], byteorder='little')
        input_type = int.from_bytes(packet[8:10], byteorder='little')
        # print(f"{input_type=}{code=}")
        if input_type:  # Check event type
            if code == 321:
                if debug:
                    print("Eraser")
                return False
            if code == 320:
                if debug:
                    print("Pen")
                return True
    else:
        return None  # In case packet is not relevant


async def websocket_handler(websocket, path, rm_host, rm_model):

    if rm_model == "reMarkable 1.0":
        device = "/dev/input/event0"
    elif rm_model == "reMarkable 2.0":
        device = "/dev/input/event1"
    else:
        raise NotImplementedError(f"Unsupported reMarkable Device: {rm_model}")
    if ssh_key:
        command = f"ssh -o ConnectTimeout=2 -i {
            ssh_key} {remarkable_user}@{rm_host} cat {device}"
    else:
        command = f"ssh -o ConnectTimeout=2 {rm_host} cat {device}"

    x = 0
    y = 0
    pressure = 0
    is_erasing = False  # Track whether the eraser is active
    proc = await asyncio.create_subprocess_shell(
        command, shell=True, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
    )
    print("Started process")

    try:
        while proc.returncode is None:
            buf = await proc.stdout.read(16)


            if len(buf) == 16:
                # Check if it's a pen or eraser event
                pen_state = is_pen(buf)
                if pen_state is False:
                    if debug:
                        print(pen_state)
                    is_erasing = True
                elif pen_state:
                    is_erasing = False
                    if debug:
                        print(is_erasing)
                # Process the packet data
                timestamp = buf[0:4]
                a = buf[4:8]
                b = buf[8:12]
                c = buf[12:16]

                typ = b[0]
                code = b[2] + b[3] * 0x100
                val = c[0] + c[1] * 0x100 + c[2] * 0x10000 + c[3] * 0x1000000

                # Absolute position.
                if typ == 3:
                    if code == 0:
                        x = val
                    elif code == 1:
                        y = val
                    elif code == 24:
                        pressure = val
                    # print(f"{x=} {y=} {code=} {pressure=} {is_erasing=}")
                    # Send different data based on whether erasing or drawing
                    await websocket.send(json.dumps({
                        "x": x,
                        "y": y,
                        "pressure": pressure,
                        "mode": "erase" if is_erasing else "draw"
                    }))

        print("Disconnected from ReMarkable.")

    finally:
        print("Disconnected from browser.")
        proc.kill()

async def http_handler(path, request):
    # only serve index file or defer to websocket handler.
    if path == "/websocket":
        return None

    elif path != "/":
        return (http.HTTPStatus.NOT_FOUND, [], "")

    body = open("index.html", "rb").read()
    headers = [
        ("Content-Type", "text/html"),
        ("Content-Length", str(len(body))),
        ("Connection", "close"),
    ]

    return (http.HTTPStatus.OK, headers, body)


def timeout_handler(signum, frame):
    raise TimeoutError("Input timed out!")


def run(rm_host=remarkable_addr, host="localhost", port=6789):
    rm_model = check(rm_host)
    bound_handler = functools.partial(
        websocket_handler, rm_host=rm_host, rm_model=rm_model
    )
    start_server = websockets.serve(
        bound_handler, host, port, ping_interval=1000, process_request=http_handler
    )
    url = f'http://{host}:{port}/'

    # Set the signal handler for the timeout
    signal.signal(signal.SIGALRM, timeout_handler)
    signal.alarm(2)  # Set the timeout to 2 seconds

    try:
        # Prompt the user to open the link
        input("Press Enter to open the link in your browser...")
        signal.alarm(0)  # Disable the alarm after successful input
    except TimeoutError:
        print(f"\nOpen {url} in your browser...")
    else:
        webbrowser.open(url)
    finally:
        asyncio.get_event_loop().run_until_complete(start_server)
        asyncio.get_event_loop().run_forever()


if __name__ == "__main__":
    print("running")
    run()
