#!/usr/bin/env python3.9
import csv
import multiprocessing
import os
import re
import shutil
import signal
import subprocess
import sys
import threading
from threading import Thread
import time
import uuid
import math
from argparse import ArgumentParser
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional
from xml.etree import ElementTree

m = "/home/mininet/mininet/util/m"
manager_procs = []

MAX_THREADS = multiprocessing.cpu_count()

CONTROLLER_API_HOSTNAME = "localhost"
CONTROLLER_API_PORT = 8080

output_file = 'results/nm_last_results.csv'


class Protocol(Enum):
    UDP = 0
    TCP = 1


@dataclass
class Metric:
    """ Class for managing a Metric with its attributes"""
    names: list[str]
    timeout: int
    probe_size: int
    train_length: int
    train_count: int
    gap: int
    protocol: Protocol
    connections: int
    time_mode: int
    max_time: int


class MetricTypes(Enum):
    RTT = Metric(names=["rtt"], timeout=3, probe_size=100, train_length=1, train_count=20, gap=50000,
                 protocol=Protocol.UDP, connections=1, time_mode=0, max_time=0)
    LOSS = Metric(names=["loss"], timeout=3, probe_size=100, train_length=1, train_count=20, gap=50000,
                  protocol=Protocol.UDP, connections=1, time_mode=0, max_time=0)
    UDP_PACK = Metric(names=["rtt", "loss"], timeout=3, probe_size=100, train_length=1, train_count=20, gap=50000,
                      protocol=Protocol.UDP, connections=1, time_mode=0, max_time=0)
    THROUGHPUT_TCP = Metric(names=["throughput_tcp"], timeout=12, probe_size=14520, train_length=1440, train_count=1,
                            gap=100000, protocol=Protocol.TCP, connections=1, time_mode=2, max_time=12)


def random():
    return int.from_bytes(os.urandom(16), byteorder="big")


def rename_switch(switch_name: str) -> str:
    ran_lower_bound = 1
    ran_upper_bound = 20

    metro_lower_bound = 21
    metro_upper_bound = 25

    access_lower_bound = 26
    access_upper_bound = 29

    core_lower_bound = 30
    core_upper_bound = 33

    internet_lower_bound = 34
    internet_upper_bound = 34

    sp = int(switch_name[1:])
    if ran_lower_bound <= sp <= ran_upper_bound:
        return create_switch_name(sp, ran_lower_bound, 'r')
    elif metro_lower_bound <= sp <= metro_upper_bound:
        return create_switch_name(sp, metro_lower_bound, 'm')
    elif access_lower_bound <= sp <= access_upper_bound:
        return create_switch_name(sp, access_lower_bound, 'a')
    elif core_lower_bound <= sp <= core_upper_bound:
        return create_switch_name(sp, core_lower_bound, 'c')
    elif internet_lower_bound <= sp <= internet_upper_bound:
        return create_switch_name(sp, internet_lower_bound, 'i')
    else:
        return f"{switch_name}"


def create_switch_name(sp, lower_bound, switch_char) -> str:
    new_sp = sp - lower_bound
    new_sp = new_sp + 1
    return f'{switch_char}{new_sp}'


def switch_from_host(path):
    ran_lower_bound = 1
    ran_upper_bound = 20
    metro_lower_bound = 21
    metro_upper_bound = 25
    access_lower_bound = 26
    access_upper_bound = 29
    core_lower_bound = 30
    core_upper_bound = 33
    internet_lower_bound = 34
    internet_upper_bound = 34

    path_first = path[0]
    path_rest = path[1:]
    switch_index = 0

    if path_first == 'r':
        switch_index = int(path_rest) + ran_lower_bound - 1
    elif path_first == 'm' and path[1] != 'a':
        switch_index = int(path_rest) + metro_lower_bound - 1
    elif path_first == 'a':
        switch_index = int(path_rest) + access_lower_bound - 1
    elif path_first == 'c' and path[1] != 'd':
        switch_index = int(path_rest) + core_lower_bound - 1
    elif path_first == 'i':
        switch_index = int(path_rest) + internet_lower_bound - 1

    if switch_index > 0:
        return 's' + str(switch_index)
    else:
        return path


def calculate_ip(p) -> str:
    if p == "cdn1":
        return "10.0.0.251"
    elif p == "cdn2":
        return "10.0.0.252"
    elif p == "cdn3":
        return "10.0.0.253"
    elif p == "ext1":
        return "10.0.0.254"
    elif p == "man1":
        return "10.0.0.241"
    elif p == "man2":
        return "10.0.0.242"
    elif p == "man3":
        return "10.0.0.243"
    elif p == "man4":
        return "10.0.0.244"
    elif p == "src1":
        return "10.0.0.249"
    elif p == "src2":
        return "10.0.0.250"
    else:
        pfirst = p[0]
        if pfirst in ['r', 'm', 'a', 'c', 'i', 's']:
            prest = switch_from_host(p)[1:]
            # prest = p[1:]
            ipfinal = 200 + int(prest)
            return f"10.0.0.{ipfinal}"
        elif pfirst == "u":
            ipfinal = p[1:]
            return f"10.0.0.{ipfinal}"


def parse_xml_text_if_exists(root, xpath):
    element = root.find(xpath)
    if element is not None:
        return element.text
    else:
        return ""


def write_data_csv(filename: str, data: list) -> None:
    with open(filename, mode='a+') as file:
        file_writer = csv.writer(file, delimiter=';', quotechar='"', quoting=csv.QUOTE_MINIMAL)
        file_writer.writerow(data)
        # print("File saved"), field


@dataclass
class Schedule:
    agent_hostname: str
    manager_hostname: str
    metric: Metric
    uuid: str = field(init=False)

    def __post_init__(self):
        self.uuid = str(uuid.uuid4())

    def measure(self):
        filename = f"/tmp/schedule-{self.uuid}.xml"
        _command = f"{m} {self.agent_hostname} /usr/netmetric/sbin/metricagent -c -f {filename} -w -l 1000 -u " \
                   f"100 -u {self.uuid} "
        # print(self)
        print(_command)
        os.system(_command)
        # time.sleep(0.42)
        self.read_store_results()
        # measurement_finish()

    def __create(self, agent_hostname: str, manager_ip: str, port: int = 12001) -> str:
        plugins = "".join(
            f'<plugins>{plugin}</plugins>\n\t\t\t ' for plugin in self.metric.names
        ).rstrip()

        return f"""<metrics>
             <ativas>
               <agt-index>1090</agt-index>
                <manager-ip>{manager_ip}</manager-ip>
                <literal-addr>{agent_hostname}</literal-addr>
                <android>1</android>
                <location>
                    <name>-</name>
                    <city>-</city>
                    <state>-</state>
                </location>
                {plugins}
                <timeout>{self.metric.timeout}</timeout>
                <probe-size>{self.metric.probe_size}</probe-size>
                <train-len>{self.metric.train_length}</train-len>
                <train-count>{self.metric.train_count}</train-count>
                <gap-value>{self.metric.gap}</gap-value>
                <protocol>{self.metric.protocol.value}</protocol>
                <num-conexoes>{self.metric.connections}</num-conexoes>
                <time-mode>{self.metric.time_mode}</time-mode>
                <max-time>{self.metric.max_time}</max-time>
                <port>{port}</port>
                <output>OUTPUT-SNMP</output>
            </ativas>\n</metrics>"""

    @staticmethod
    def __save(filename: str, schedule: str) -> bool:
        with open(filename, 'w+') as file:
            file.write(schedule)
            return True

    def create_and_save(self):
        schedule_filename = f"/tmp/schedule-{self.uuid}.xml"
        manager_ip = calculate_ip(self.manager_hostname)
        schedule = self.__create(self.agent_hostname, manager_ip)
        self.__save(schedule_filename, schedule)

    def read_store_results(self) -> None:
        filename = f"agent-{self.uuid}.xml"
        root = ElementTree.parse(filename).getroot()

        current_timestamp = str(datetime.now())
        if self.metric is not None:
            for name in self.metric.names:
                upload_avg = root.findtext(f"./ativas[@metrica=\"{name}\"]/upavg", default='')
                download_avg = root.findtext(f"./ativas[@metrica=\"{name}\"]/downavg", default='')

                data = [
                    self.agent_hostname,
                    self.manager_hostname,
                    current_timestamp,
                    self.uuid,
                    name,
                    upload_avg,
                    download_avg,
                ]

                self.store_result(output_file, data)

                if name == 'rtt':
                    link_data = [self.agent_hostname, self.manager_hostname, (float(upload_avg) / 2), 0, 0, ]
                    self.store_result("link_last_results.csv", link_data)
                    link_data = [self.manager_hostname, self.agent_hostname, (float(upload_avg) / 2), 0, 0, ]
                    self.store_result("link_last_results.csv", link_data)

            shutil.move(f"agent-{self.uuid}.xml", f"./results/xml/agent-{self.uuid}.xml")

    @staticmethod
    def store_result(filename: str, data: list) -> bool:
        with open(filename, mode='a+') as file:
            file_writer = csv.writer(file, delimiter=';', quotechar='"', quoting=csv.QUOTE_MINIMAL)
            file_writer.writerow(data)
            return True

    def __str__(self):
        return f"Schedule [uuid={self.uuid}, agent={self.agent_hostname}, manager={self.manager_hostname}, metric={self.metric.names}]"


_schedule_queue: list[Schedule] = list[Schedule]()
_current_schedule: Optional[Schedule] = None


def enqueue_schedule(schedule: Schedule) -> None:
    global _schedule_queue
    print("Enqueue Schedule!")
    _schedule_queue.append(schedule)
    rotate()


def rotate() -> None:
    global _current_schedule
    global _schedule_queue
    if _current_schedule is None:
        if _schedule_queue:
            _current_schedule = _schedule_queue.pop(0)
            print(f"Queue: {_schedule_queue}, Current Schedule = {_current_schedule}")
            _current_schedule.measure()
        else:
            print("No schedules on queue!")
    else:
        print("Couldn't execute current schedule since a measure is already running")


def measurement_finish() -> None:
    global _current_schedule
    global _schedule_queue
    print("Measure Finished!")
    _current_schedule = None
    rotate()


_active_meas_services: dict[int, Thread] = {}
_finished_meas_services: dict[int, Thread] = {}


def measurement_service_started(meas_service_thread: Thread) -> None:
    print(f'Added {meas_service_thread.ident=} to list')
    _active_meas_services.update({meas_service_thread.ident: meas_service_thread})


def measurement_service_finished(meas_service_thread: Thread) -> None:
    print(f'Removed {meas_service_thread.ident=} to list')
    _active_meas_services.pop(meas_service_thread.ident)
    _finished_meas_services.update({meas_service_thread.ident: meas_service_thread})

    if are_all_measurement_service_finished():
        print("All measurements are finished. Let's finish it all")
        kill_all_managers()
        sys.exit(0)


def are_all_measurement_service_finished() -> bool:
    return len(_active_meas_services) == 0 and len(_finished_meas_services) > 0


def measurement_service(agent_hostname: str, manager_hostname: str, first_trigger_time_seconds,
                        metric: Metric, period_in_seconds: float):
    """
    Service whose responsibility is create the measurement schedule, enqueue it and
    waiting for measure polling time
    """

    # First of all, must wait the first trigger time
    # first_trigger_seconds = first_trigger_time_seconds + (3 + (random() % 20))
    first_trigger_seconds = first_trigger_time_seconds
    print(f'Waiting for {first_trigger_seconds} s for stating this measure')
    time.sleep(first_trigger_seconds)

    # time.sleep(period_in_seconds)
    if period_in_seconds > 0:
        while True:
            schedule = Schedule(agent_hostname, manager_hostname, metric)
            schedule.create_and_save()
            # enqueue_schedule(schedule)
            schedule.measure()

            time.sleep(period_in_seconds)
    else:
        schedule = Schedule(agent_hostname, manager_hostname, metric)
        schedule.create_and_save()
        schedule.measure()
    measurement_service_finished(threading.current_thread())


def is_manager_busy(manager: str) -> Optional[int]:
    """
    Returns if a manager port is busy (metricmanager already load), the process' pid
    """
    manager_port = "12055"
    netstat_results = subprocess.Popen(f"{m} {manager} netstat -anp", shell=True, stdout=subprocess.PIPE).stdout
    netstat_results = netstat_results.read().decode().split('\n')  # Separates lines
    netstat_results.pop(0)  # Skipping the first line
    netstat_results.pop(0)  # The second one
    for result in netstat_results:
        formatted_result = [r for r in result.replace(' \t', '').split(' ') if r != '']
        if len(formatted_result) >= 7 and formatted_result[3].find(manager_port) != -1:
            pid_busy_port = re.match(r'(\d+)/\w+', formatted_result[6])
            if pid_busy_port is not None:
                return int(re.match(r'(\d+)/\w+', formatted_result[6]).group(1))
    return None


def interruption_handler(sig, frame):
    print('Sig INT detected!')
    print('Killing all Managers processes...')
    kill_all_managers()
    sys.exit(0)


def kill_all_managers():
    for man_proc in manager_procs:
        print(f'Sig KILL send to [PID={man_proc.pid}]')
        os.killpg(man_proc.pid, signal.SIGTERM)


def save_pid(pid: int, pids_file: str) -> None:
    with open(pids_file, mode="a+") as pfile:
        pfile.write(f"{pid}\n")


def run_unitary_measure(agent_hostname, manager_hostname, first_trigger_time_seconds) -> None:
    save_pid(os.getpid(), "/tmp/pids_running.txt")

    mes_thread = Thread(target=measurement_service, args=(agent_hostname, manager_hostname,
                                                          first_trigger_time_seconds,
                                                          MetricTypes.RTT.value,
                                                          -1,))
    mes_thread.start()
    measurement_service_started(mes_thread)


def start_managers(managers: list[str] = None):
    if managers is None:
        managers = ["man1", "man2", "man3", "man4"]

    print("Starting managers...")
    signal.signal(signal.SIGINT, interruption_handler)
    for manager in managers:
        run_manager(manager)
    print("Started manager... Let's wait them to wake up")
    # time.sleep(60)
    print("Ok, Managers should be awake now. Let's get start the measurements!")


def run_manager(manager_hostname: str, uses_manager: bool = True):
    renamed_manager = manager_hostname if uses_manager else rename_switch(manager_hostname)
    pid_manager_port_busy = is_manager_busy(renamed_manager)
    print(f"Is manager {renamed_manager} busy: {pid_manager_port_busy is not None}")
    while pid_manager_port_busy is not None:
        print(f"Waiting for manager {renamed_manager} free the port up...")
        os.system(f'{m} {renamed_manager} kill -9 {pid_manager_port_busy}')
        time.sleep(5)
        pid_manager_port_busy = is_manager_busy(renamed_manager)
    # Starts metric manager first
    command = f"taskset -c {run_manager.core} {m} {renamed_manager} /usr/netmetric/sbin/metricmanager -c &"
    print(command)
    os.system(command)
    # Run Netmetric Manager using subprocess
    # manager_process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, shell=True,
    #                                    preexec_fn=os.setsid)
    # manager_procs.append(manager_process)
    time.sleep(1)
    run_manager.core = run_manager.core + 1 if run_manager.core < (MAX_THREADS - 1) else 0


run_manager.core = 0


def find_managers(__file: str):
    with open(__file) as __measurement_profiles:
        __csv_reader = csv.reader(__measurement_profiles, delimiter=";")
        __managers = ([*{__row[1]
                         for __row_count, __row in enumerate(__csv_reader)
                         if __row and __row_count != 0}])
        __managers.sort()
        return __managers


if __name__ == '__main__':
    # Informing script arguments
    parser = ArgumentParser(
        description='Performs a repeated measure in a pair src-dst given period of each measure type')
    # parser.add_argument("-f", "--fast", help="fast initial trigger", action="store_true")
    # parser.add_argument("-v", "--verbose", help="verbose mode", action="store_true")
    parser.add_argument("-f", "--file", help="Open from a file", type=str, nargs='?')
    parser.add_argument("-o", "--output", help='File to store results', type=str, nargs='?')
    opts, rem_args = parser.parse_known_args()
    if opts.file is None:
        parser.add_argument("-m", "--manager", help="Uses Manager", action="store_true")
        parser.add_argument("-sm", "--start_metricman", help="Start Netmetric Manager on Manager", action="store_true")
        parser.add_argument("-stt", "--start_trigger_time", type=float, nargs='?',
                            help="How long it takes to start the measures")
        parser.add_argument("--rounds", type=int, nargs='?',
                            help="How many measures should be done")
        parser.add_argument("agent_hostname", type=str, help="Agent hostname")
        parser.add_argument("manager_hostname", type=str, help="Manager hostname")
        args = parser.parse_args(rem_args, opts)

        # Read parameters from input
        tp_period_seconds = args.throughput_tcp_period * 60
        rtt_period_seconds = args.rtt_period * 60
        loss_period_seconds = args.loss_period * 60
        first_trigger_time_seconds = args.first_trigger_time * 60
        agent_hostname = args.agent_hostname
        manager_hostname = args.manager_hostname
        uses_manager = args.manager
        start_manager = args.start_metricman
        output_file = args.output
        rounds = args.rounds if args.rounds is not None else math.inf
        print(rounds)

        if not os.path.exists("results"):
            os.makedirs("results")
        if not os.path.exists("results/xml"):
            os.makedirs("results/xml")

        if start_manager:
            run_manager(manager_hostname)

        # Save parent's pid
        if os.path.exists("/tmp/pids_running"):
            os.remove("/tmp/pids_running.txt")
        save_pid(os.getpid(), "/tmp/pids_running.txt")

        # run_repeated_measure(agent_hostname, manager_hostname, first_trigger_time_seconds, tp_period_seconds,
        #                      rtt_period_seconds, loss_period_seconds)
    else:
        args = parser.parse_args()
        file_input = args.file
        output_file = args.output

        # print(find_managers(file_input), len(find_managers(file_input)))
        start_managers(find_managers(file_input))

        # time.sleep(30)

        # Save parent's pid
        if os.path.exists("/tmp/pids_running"):
            os.remove("/tmp/pids_running.txt")
        save_pid(os.getpid(), "/tmp/pids_running.txt")

        with open(file_input) as measurement_profiles:
            csv_reader = csv.reader(measurement_profiles, delimiter=";")
            for line_number, line in enumerate(csv_reader):

                # Skip blank lines and header line
                if line is not None and line_number != 0:
                    # Read parameters from file
                    agent_hostname = line[0]
                    manager_hostname = line[1]
                    first_trigger_time_seconds = float(line[2]) * 60

                    run_unitary_measure(agent_hostname, manager_hostname, first_trigger_time_seconds)