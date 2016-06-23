#!/usr/bin/python

#      Copyright 2015, Schuberg Philis BV
#
#      Licensed to the Apache Software Foundation (ASF) under one
#      or more contributor license agreements.  See the NOTICE file
#      distributed with this work for additional information
#      regarding copyright ownership.  The ASF licenses this file
#      to you under the Apache License, Version 2.0 (the
#      "License"); you may not use this file except in compliance
#      with the License.  You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
#      Unless required by applicable law or agreed to in writing,
#      software distributed under the License is distributed on an
#      "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY
#      KIND, either express or implied.  See the License for the
#      specific language governing permissions and limitations
#      under the License.

# We depend on these
import socket
import sys
import time
import os
import hypervisor

# Fabric
from fabric.api import *
from fabric import api as fab
from fabric import *

# Set user/passwd for fabric ssh
env.user = 'root'
env.password = 'password'
env.forward_agent = True
env.disable_known_hosts = True
env.parallel = False
env.pool_size = 1

# Supress Fabric output by default, we will enable when needed
output['debug'] = False
output['running'] = False
output['stdout'] = False
output['stdin'] = False
output['output'] = False
output['warnings'] = False


# Class to handle XenServer patching
class xenserver(hypervisor):

    def __init__(self, ssh_user='root', threads=5):
        self.ssh_user = ssh_user
        self.threads = threads
        self.mountpoint = ""

    # Wait for hypervisor to become alive again
    def check_connect(self, host):
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        print "Note: Waiting for " + host.name + "(" + host.ipaddress + ") to return"
        while s.connect_ex((host.ipaddress, 22)) > 0:
            # Progress indication
            sys.stdout.write(".")
            sys.stdout.flush()
            time.sleep(5)
        # Remove progress indication
        sys.stdout.write("\033[F")
        print "Note: Host " + host.name + " responds to SSH again!                           "
        print "Note: Waiting until we can successfully run a XE command against the cluster.."
        while self.check_xapi(host) is False:
            # Progress indication
            sys.stdout.write(".")
            sys.stdout.flush()
            time.sleep(5)
        # Remove progress indication
        sys.stdout.write("\033[F")
        print "Note: Host " + host.name + " is able to do XE stuff again!                                  "
        return True

    # Check if we can use xapi
    def check_xapi(self, host):
        try:
            with settings(host_string=self.ssh_user + "@" + host.ipaddress):
                with warn_only():
                    result = fab.run("xe host-enable host=" + host.name)
                if result.return_code == 0:
                    return True
                else:
                    return False
        except:
            return False

    # Return host of poolmaster
    def get_poolmaster(self, host):
        try:
            with settings(host_string=self.ssh_user + "@" + host.ipaddress):
                return fab.run("xe host-list uuid=$(xe pool-list params=master | awk {'print $5'}) params=name-label | awk {'print $5'} | tr -d '\n'")
        except:
            return False

    # Get current patchlevel
    def get_patch_level(self, host):
        try:
            with settings(host_string=self.ssh_user + "@" + host.ipaddress):
                return fab.run("for p in $(xe patch-list | grep XS.*E | awk {'print $4'} | tr -d \" \" |\
                sort | tr '\n' ' '); do echo -n $p \"(\"; xe patch-list name-label=$p params=hosts |\
                awk -F: {'print $2'} | tr -cd , | awk {'print $1 \",\"'} | tr -d '\n' | wc -c | tr -d '\n'; echo -n \") \"; done")
        except:
            return False

    def check_patch(self):
        pass

    def host_check_reboot_needed(self):
        pass

    # Put a host to service in XenServer
    def host_enable(self, host):
        print "Note: Enabling host " + host.name
        try:
            with settings(host_string=self.ssh_user + "@" + host.ipaddress):
                return fab.run("xe host-enable host=" + host.name)
        except:
            return False

    # Put a host to maintenance in XenServer
    def host_disable(self, host):
        print "Note: Disabling host " + host.name
        try:
            with settings(host_string=self.ssh_user + "@" + host.ipaddress):
                return fab.run("xe host-disable host=" + host.name)
        except:
            print "Warning: host_disable returned false for " + host.name
            return False

    # Live migrate all VMS off of a hypervisor
    def host_evacuate(self, host):
        print "Note: Evacuating host " + host.name + " @ " + time.strftime("%Y-%m-%d %H:%M")
        print "Note: Migration progress will appear here.."
        try:
            with settings(host_string=self.ssh_user + "@" + host.ipaddress):
                fab.run("nohup python /tmp/xenserver_parallel_evacuate.py --exec --threads " + str(self.threads) + " >& /dev/null < /dev/null &", pty=False)

            while True:
                numer_of_vms = self.host_get_vms(host)
                # Overwrite previous lin_
                sys.stdout.write("\033[F")
                print "Progress: On host " + host.name + " there are " + numer_of_vms + " VMs left to be migrated.."
                if int(numer_of_vms) == 0:
                    break
                time.sleep(5)
            print "Note: Done evacuating host " + host.name + " @ " + time.strftime("%Y-%m-%d %H:%M")
            return True
        except:
            return False

    # Reboot a host when all conditions are met
    def host_reboot(self, host, halt_hypervisor=False):
        # Disbale host
        if self.host_disable(host) is False:
            print "Error: Disabling host " + host.name + " failed."
            return False

        # Then evacuate it
        if self.host_evacuate(host) is False:
            print "Error: Evacuating host " + host.name + " failed."
            return False

        # Count VMs to be sure
        if self.host_get_vms(host) != "0":
            print "Error: Host " + host.name + " not empty, cannot reboot!"
            return False
        print "Note: Host " + host.name + " has no VMs running, continuing"

        # Finally reboot it
        try:
            with settings(host_string=self.ssh_user + "@" + host.ipaddress):
                if halt_hypervisor:
                    print "Note: Halting host " + host.name
                    fab.run("xe host-shutdown host=" + host.name)
                else:
                    print "Note: Rebooting host " + host.name
                    fab.run("xe host-reboot host=" + host.name)
        except:
            print "Error: Rebooting host " + host.name + " failed."
            return False

        # Check the host is really offline
        self.check_offline(host)

        # Wait until the host is back
        self.check_connect(host)

        # Enable host
        if self.host_enable(host) is False:
            print "Error: Enabling host " + host.name + " failed."
            return False

    # Get VM count of a hypervisor
    def host_get_vms(self, host):
        try:
            with settings(host_string=self.ssh_user + "@" + host.ipaddress):
                return fab.run("xe vm-list resident-on=$(xe host-list params=uuid \
                name-label=$HOSTNAME --minimal) \
                params=name-label,memory-static-max is-control-domain=false | \
                tr '\\n' ' ' | sed 's/name-label/\\n/g' | \
                awk {'print $4 \",\" $8'} | sed '/^,$/d'| wc -l")
        except:
            return False

    # Enable XenServer poolHA
    def pool_ha_enable(self, host):
        print "Note: Enabling HA"
        try:
            with settings(host_string=self.ssh_user + "@" + host.ipaddress):
                if fab.run("cat /etc/redhat-release | awk '{ $3 = substr($3,1,3); print $3 }'") == "6.2":
                    return fab.run("xe pool-ha-enable heartbeat-sr-uuids=$(xe sr-list type=nfs params=uuid --minimal) ha-config:timeout=180 ha-config:ha-host-failures-to-tolerate=1")
                else:
                    return fab.run("xe pool-ha-enable heartbeat-sr-uuids=$(xe sr-list type=nfs params=uuid --minimal) ha-config:timeout=180; xe pool-param-set uuid=$(xe pool-list params=uuid --minimal) ha-host-failures-to-tolerate=1")
        except:
            return False

    # Disable XenServer poolHA
    def pool_ha_disable(self, host):
        print "Note: Disabling HA"
        if self.pool_ha_check(host):
            try:
                with settings(host_string=self.ssh_user + "@" + host.ipaddress):
                    return fab.run("xe pool-ha-disable")
            except:
                return False
        else:
            return "Error"

    # Check the current state of HA
    def pool_ha_check(self, host):
        try:
            with settings(host_string=self.ssh_user + "@" + host.ipaddress):
                if fab.run("xe pool-list params=ha-enabled | awk {'print $5'} | tr -d '\n'") == "true":
                    return True
                else:
                    return False
        except:
            return "Error"

    # Make sure hosts are put to Enabled again
    def roll_back(self, host):
        print "Note: Problem detected, rolling back."

        # Enable host
        if self.host_enable(host) is False:
            print "Error: Enabling host " + host.name + " failed."
            return False

    # Upload check scripts
    def put_scripts(self, host):
        try:
            with settings(host_string=self.ssh_user + "@" + host.ipaddress):
                put('xenserver_check_bonds.py',
                    '/tmp/xenserver_check_bonds.py', mode=0755)
                put('xenserver_fake_pvtools.sh',
                    '/tmp/xenserver_fake_pvtools.sh', mode=0755)
                put('xenserver_parallel_evacuate.py',
                    '/tmp/xenserver_parallel_evacuate.py', mode=0755)
            return True
        except:
            print "Warning: Could not upload check scripts to host " + host.name + ". Continuing anyway."
            return False

    # Eject CDs
    def eject_cds(self, host):
        print "Note: We're ejecting all mounted CDs on this cluster."
        try:
            with settings(host_string=self.ssh_user + "@" + host.ipaddress):
                return fab.run("for vm in $(xe vbd-list type=CD empty=false params=vm-uuid --minimal |\
                    tr \",\" \" \"); do echo \"xe vm-cd-eject uuid=\"$vm; done | sh")
        except:
            return False

    # Fake PV tools
    def fake_pv_tools(self, host):
        print "Note: We're faking the presence of PV tools of all vm's reporting no tools on hypervisor " + host.name
        try:
            with settings(host_string=self.ssh_user + "@" + host.ipaddress):
                return fab.run("xe vm-list PV-drivers-up-to-date='<not in database>' is-control-domain=false\
                    resident-on=$(xe host-list name-label=$HOSTNAME --minimal) params=uuid --minimal\
                    |tr ', ' '\n'| grep \"-\" | awk {'print \"/tmp/xenserver_fake_pvtools.sh \" $1'} | sh")
        except:
            return False

    # Get bond status
    def get_bond_status(self, host):
        try:
            with settings(host_string=self.ssh_user + "@" + host.ipaddress):
                return fab.run("python /tmp/xenserver_check_bonds.py | awk {'print $1'} | tr -d \":\"")
        except:
            return False

    # Export a VDI to a given path
    def export_volume(self, host, vdi_uuid):
        export_path = self.get_migration_path() + vdi_uuid + ".vhd"
        print "Note: We're exporting disk with UUID %s to %s" % (vdi_uuid, export_path)
        try:
            with settings(host_string=self.ssh_user + "@" + host.ipaddress):
                command = "xe vdi-export uuid=%s filename=%s format=vhd" % (vdi_uuid, export_path)
                return fab.run(command)
        except:
            return False

    def prepare_xenserver(self, xenhost):
        result = self.create_migration_nfs_dir(xenhost)
        if not result:
            print "Error: Could not prepare the export folder on host " + xenhost
            sys.exit(1)
        print "Note received this result:" + str(result)
        return True

    def find_nfs_mountpoint(self, host):
        print "Note: Looking for NFS mount on XenServer"
        if self.mountpoint is not None:
            return self.mountpoint
        try:
            with settings(host_string=self.ssh_user + "@" + host.ipaddress):
                command = "xe pbd-list sr-uuid=$(xe sr-list type=nfs params=uuid --minimal) params=sr-uuid" \
                          " host-name-label=${HOSTNAME} --minimal"
                srid = fab.run(command)
                self.mountpoint = "/var/run/sr-mount/" + srid + "/"
                print "Note: Found " + str(self.mountpoint)
                return self.mountpoint
        except:
            return False

    def get_migration_path(self):
        return self.mountpoint + "migration/"

    def create_migration_nfs_dir(self, host):
        self.find_nfs_mountpoint(host)
        print "Note: Looking for migration folder"
        try:
            with settings(host_string=self.ssh_user + "@" + host.ipaddress):
                command = "mkdir -p " + self.mountpoint
                return fab.run(command)
        except:
            return False
