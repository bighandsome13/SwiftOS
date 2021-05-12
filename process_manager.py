#!/usr/bin/env python
# -*- coding: utf-8 -*-

import os
import time
import copy
import logging
from config import *


class PCB(object):
    """ ProcessControlBlock
    Atrributes:
        pid,pname,parentid,priority,create_time,status,
        tasklist: 该进程待执行的任务
        msize: 该进程所占用的内存大小
    """
    def __init__(self, pid, pname, priority, content, msize):
        self.pid = pid
        self.pname = pname
        self.priority = priority  # 0 is higher than 1
        self.msize = msize
        self.parent_id = -1
        self.child_pid_list = []
        self.create_time = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime())
        self.status = 'ready'

        self.tasklist = []
        for task in content:
            info = str.split(task)
            if len(info) > 1:
                if info[0] == 'cpu':
                    info[1] = float(info[1])
                else:
                    info[1] = int(info[1])
            self.tasklist.append(info)  # example: [[printer, 18], [cpu, 170]]
        self.current_task = 0


class ProcessManager(object):
    """ Provide functions to manage process"""
    def __init__(self, memory_manager):
        """ 
        Args:
            pid_no: 下个进程的序号
            pcblist: 被管理进程的PCB
            ready_queue: 就绪队列，分为三个优先级
            waiting_queue:等待队列
            p_running：正在运行的进程，引用pcb，同一时间只有一个
            memory_manager: 每个进程所对应的内存及其管理器
            mem_of_pid：每个进程所对应的内存号
        """
        self.pid_no = 0
        self.pcblist = []
        self.ready_queue = [[] for i in range(3)]
        self.waiting_queue = []
        self.p_running = None
        self.is_running = False
        self.memory_manager = memory_manager
        self.time_slot = time_slot_conf
        self.priority = priority_conf
        self.mem_of_pid = {}


    def create(self, exefile):
        """ 打开程序文件创建进程 """
        if exefile['type'][0] != 'e':
            self.error_handler('exec')
        else:
            mem_no = self.memory_manager.allocate_memory(
                self.pid_no, int(exefile['size']))
            if mem_no == -1:
                self.error_handler('mem')
            else:
                pcb = PCB(self.pid_no, exefile['name'], exefile['priority'],
                          exefile['content'], int(exefile['size']))
                self.pcblist.append(pcb)
                self.mem_of_pid[pcb.pid] = mem_no
                print(f'[进程名 {pcb.pname}]创建成功')
                print("批处理任务开始执行，请在日志文件查看详细信息")
                logging.info(f'[pid {pcb.pid}] process created successfully.')
                self.ready_queue[exefile['priority']].append(pcb.pid)
                self.pid_no += 1

    def fork(self):
        """ 创建子进程 """
        child_msize = self.p_running.msize
        mem_no = self.memory_manager.allocate_memory(self.pid_no, child_msize)
        if mem_no == -1:
            self.error_handler('mem')
        else:
            # self.p_running.current_task += 1
            # 初始化子进程pcb
            child_pcb = copy.deepcopy(self.p_running)
            child_pcb.pid = self.pid_no
            child_pcb.parent_id = self.p_running.pid
            child_pcb.create_time = time.strftime('%Y-%m-%d %H:%M:%S',
                                                  time.localtime())
            # 子进程下一task
            child_pcb.current_task += 1

            self.pcblist.append(child_pcb)
            self.ready_queue[child_pcb.priority].append(child_pcb.pid)
            self.pid_no += 1
            self.p_running.child_pid_list.append(child_pcb)
            # sys.stdout.write('\033[2K\033[1G\033[9D')  # to remove extra output \$
            logging.info(
                f'[pid {child_pcb.pid}] process forked successfully by [pid {child_pcb.parent_id}].'
            )

    def dispatch(self):
        """ 调度进程，ready->running """
        self.p_running = None
        for level in range(0, len(self.ready_queue)):
            # 就绪队列不为空
            if self.ready_queue[level]:
                self.p_running = self.pcblist[self.ready_queue[level][0]]
                self.ready_queue[level].pop(0)
                self.p_running.status = 'running'
                break

    def timeout(self):
        """ 时间片用尽，running->ready """
        time.sleep(self.time_slot)
        if self.p_running:
            # 进程进入就绪队列继续等待执行
            self.p_running.status = 'ready'
            level = self.p_running.priority
            self.ready_queue[level].append(self.p_running.pid)

    def io_wait(self):
        """ 等待io事件，进程阻塞，running->waiting """
        self.p_running.status = 'waiting'
        io_time = self.p_running.tasklist[self.p_running.current_task][1]
        # waiting queue： [[pid1, time], [pid2, time]]
        self.waiting_queue.append([self.p_running.pid, io_time])

    def io_completion(self, pid):
        """ io完成，进程被唤醒，waiting->ready """
        if self.keep_next_task(pid) == True:
            self.pcblist[pid].status = 'ready'
            level = self.pcblist[pid].priority
            self.ready_queue[level].append(pid)

    def kill(self, pid):
        """ kill进程，释放所属资源. 考虑和run守护进程的互斥 """
        if pid not in [pcb.pid for pcb in self.pcblist]:
            self.error_handler('kill_nopid', pid)
        else:
            status = self.pcblist[pid].status
            if status == 'terminated':
                self.error_handler('kill_already', pid)
            else:
                if status == 'ready':
                    level = self.pcblist[pid].priority
                    self.ready_queue[level].remove(pid)
                elif status == 'running':
                    self.p_running = None
                elif status == 'waiting':
                    for index in range(len(self.waiting_queue)):
                        if self.waiting_queue[index][0] == pid:
                            self.waiting_queue.pop(index)
                self.pcblist[pid].status = 'terminated'
                # 释放内存资源
                self.memory_manager.free_memory(pid)
                print(f'[pid  # {pid}] is killed successfully!')

    def keep_next_task(self, pid):
        # 若当前是进程的最后一条task，转为结束态
        if self.pcblist[pid].current_task == len(
                self.pcblist[pid].tasklist) - 1:
            if (self.memory_manager.free_memory(pid)):
                # 若进程存在于就绪队列，从就绪队列取出
                if pid in self.ready_queue[self.pcblist[pid].priority]:
                    self.ready_queue[self.pcblist[pid].priority].remove(pid)
                self.pcblist[pid].status = 'terminated'
                logging.info(f'[Pid #{pid}] terminated!')
                # 就绪队列是否为空, 判断文件执行完成
                exe_completed = True
                for pro in self.pcblist:
                    if pro.status != 'terminated':
                        exe_completed = False
                        break
                if (exe_completed):
                    logging.info("------------------------本文件执行完成！")
            else:
                # 该进程对应的内存空间已被释放
                logging.info(
                    f'Failed to free, the memory of [Pid {pid}] has been freed.'
                )
            return False
        else:  # 继续下一个task
            self.pcblist[pid].current_task += 1
            return True

    def print_process_status(self):
        """ 获取当前进程状态 """
        running = False
        for pro in self.pcblist:
            if pro.status != 'terminated':
                print("[pid #%5d] name: %-10s status: %-20s create_time: %s" %
                      (pro.pid, pro.pname, pro.status, pro.create_time))
                running = True
        if not running:
            print("No process is running currently")

    def input_handler(self):
        """ 处理命令行输入 """
        while True:
            s = input("\$").split()
            if s[0] == 'ps':
                self.print_process_status()
            elif s[0] == 'rs':
                self.print_resource_status()
            elif s[0] == 'kill':
                self.kill(int(s[1]))
            elif s[0] == 'exec':
                # 需配合文件管理模块
                exefile = self.file_manager.get_file(file_path=s[1],
                                                     seek_algo=seek_algo)
                self.create(exefile)
            else:
                print('command not found: %s' % s[0])

    def start_manager(self):
        """ 主逻辑，启动模块并运行 """
        self.is_running = True
        while self.is_running:
            self.dispatch()
            if self.p_running:
                # current不能为-1
                task = self.p_running.tasklist[self.p_running.current_task]
                if task[0] == 'fork':
                    self.fork()
                    # 计时，进ready
                    self.timeout()
                    # 继续下一task，若当前进程task全部完成，则重新调度
                    self.keep_next_task(self.p_running.pid)
                    continue
                elif task[0] == 'access':
                    self.memory_manager.access_memory(self.p_running.pid,
                                                      task[1])
                    logging.info(
                        f'[pid {self.p_running.pid}] process accessed [memory {task[1]}] successfully.'
                    )
                    self.timeout()
                    self.keep_next_task(self.p_running.pid)
                    continue
                elif task[0] == 'printer':
                    self.io_wait()
                    continue
                elif task[0] == 'cpu':
                    if task[1] > self.time_slot:
                        self.timeout()
                        task[1] -= self.time_slot
                        continue
                    else:
                        time.sleep(task[1])
                        logging.info(
                            f'[pid {self.p_running.pid}] process completed a cpu task successfully.'
                        )
                        if self.keep_next_task(self.p_running.pid) == True:
                            self.p_running.status = 'ready'
                            level = self.p_running.priority
                            self.ready_queue[level].append(self.p_running.pid)
                            continue

    def error_handler(self, type, pid=-1):
        if type == 'mem':
            print("Failed to create new process: No enough memory.")
        elif type == 'exec':
            print('Failed to exucute: Not an executable file.')
        elif type == 'kill_nopid':
            print(f'kill: kill [pid #{pid}] failed: no such process')
        elif type == 'kill_already':
            print(
                f'kill: kill [pid #{pid}] failed: the process is already terminiated'
            )

log_path = os.getcwd() + os.sep + 'logging' + os.sep + 'log.txt'
logging.basicConfig(
    level=logging.INFO,
    filename=log_path,
    filemode='w',  # w就是写模式，a是追加模式
    format='%(asctime)s - %(message)s')

'''
if __name__ == '__main__':
    memory = MemoryManager(mode=memory_management_mode,page_size=memory_page_size,
                                                page_number=memory_page_number,
                                                physical_page=memory_physical_page_number)
    pm = ProcessManager(memory)
    # 三个线程负责输入、后台逻辑、io设备运行
    input_thread = threading.Thread(target=pm.input_handler)
    logical_thread = threading.Thread(target=pm.start_manager)
    IOdevice_thread = threading.Thread(target=pm.io_device_handler)

    input_thread.start()
    logical_thread.setDaemon(True)
    IOdevice_thread.setDaemon(True)
    logical_thread.start()
    IOdevice_thread.start()
'''