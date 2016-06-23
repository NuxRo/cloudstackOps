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

# Class to talk to CloudStack SQL database
# Remi Bergsma - rbergsma@schubergphilis.com

# Import the class we depend on
from cloudstackopsbase import *
# Import our dependencies
import mysql.connector
from mysql.connector import errorcode


class CloudStackSQL(CloudStackOpsBase):

    # Connect MySQL Cloud DB
    def connectMySQL(self, mysqlhost, mysqlpassword=''):
        # Try to lookup password if not supplied
        if not mysqlpassword:
            # Try to read MySQL settings from config file
            try:
                self.configfile = os.getcwd() + '/config'
                config = ConfigParser.RawConfigParser()
                config.read(self.configfile)
                mysqlpassword = config.get(mysqlhost, 'mysqlpassword')
            except:
                print "Error: Tried to read password from config file 'config', but failed."
                print "Error: Make sure there is a section [" + mysqlhost + "] with mysqlpassword=password or specify password on the command line."
                sys.exit(1)

        config = {
            'user': 'cloud',
            'password': mysqlpassword,
            'host': mysqlhost,
            'database': 'cloud',
            'raise_on_warnings': True,
        }

        try:
            conn = mysql.connector.connect(**config)
        except mysql.connector.Error as err:
            if err.errno == errorcode.ER_ACCESS_DENIED_ERROR:
                print("Something is wrong with your user name or password")
                return 1
            elif err.errno == errorcode.ER_BAD_DB_ERROR:
                print("Database does not exists")
                return 1
            else:
                print(err)
                return 1

        self.conn = conn
        return 0

    # Disconnect MySQL connection
    def disconnectMySQL(self):
        self.conn.close()

    # list HA Workers
    def getHAWorkerData(self, hypervisorName):
        if not self.conn:
            return 1

        if len(hypervisorName) > 0:
            hypervisorNameWhere = " AND host.name = '" + hypervisorName + "'"
        else:
            hypervisorNameWhere = ""

        cursor = self.conn.cursor()
        cursor.execute("SELECT \
        d.name AS domain, \
        vm.name AS vmname, \
        ha.type, \
        vm.state, \
        ha.created, \
        ha.taken, \
        ha.step, \
        host.name AS hypervisor, \
        ms.name AS mgtname, \
        ha.state \
        FROM cloud.op_ha_work ha \
        LEFT JOIN cloud.mshost ms ON ms.msid=ha.mgmt_server_id \
        LEFT JOIN cloud.vm_instance vm ON vm.id=ha.instance_id \
        LEFT JOIN cloud.host ON host.id=ha.host_id \
        LEFT JOIN cloud.domain d ON vm.domain_id = d.id \
        WHERE ha.created > DATE_SUB(NOW(), INTERVAL 1 DAY) " +
                       hypervisorNameWhere + " \
        ORDER BY domain,ha.created desc \
        ;")
        result = cursor.fetchall()
        cursor.close()

        return result

    # list Async jobs
    def getAsyncJobData(self):
        if not self.conn:
            return 1

        cursor = self.conn.cursor()
        cursor.execute("SELECT user.username, \
        account.account_name, \
        instance_name, \
        vm_instance.state as vm_state, \
        job_cmd, job_dispatcher, async_job.created, \
        mshost.name, async_job.id, related \
        FROM async_job \
        LEFT JOIN user ON user_id = user.id \
        LEFT JOIN account ON async_job.account_id = account.id \
        LEFT JOIN vm_instance ON instance_id = vm_instance.id \
        LEFT JOIN mshost ON job_init_msid = mshost.id \
        WHERE job_result is null;")
        result = cursor.fetchall()
        cursor.close()

        return result

    # list ip adress info
    def getIpAddressData(self, ipaddress):
        if not self.conn:
            return 1

        cursor = self.conn.cursor()
        cursor.execute("SELECT \
        vpc.name, \
        'n/a' AS 'mac_address', \
        user_ip_address.public_ip_address, \
        'n/a' AS 'netmask', \
        'n/a' AS 'broadcast_uri', \
        networks.mode, \
        user_ip_address.state, \
        user_ip_address.allocated as 'created', \
        'n/a' AS 'vm_instance' \
        FROM cloud.user_ip_address \
        LEFT JOIN vpc ON user_ip_address.vpc_id = vpc.id \
        LEFT JOIN networks ON user_ip_address.source_network_id = networks.id \
        WHERE public_ip_address like '%" + ipaddress  + "%' \
        UNION \
        SELECT networks.name, \
        nics.mac_address, \
        nics.ip4_address, \
        nics.netmask, \
        nics.broadcast_uri, \
        nics.mode, \
        nics.state, \
        nics.created, \
        vm_instance.name \
        FROM cloud.nics, cloud.vm_instance, \
        cloud.networks \
        WHERE nics.instance_id = vm_instance.id \
        AND nics.network_id = networks.id \
        AND ip4_address \
        LIKE '%" + ipaddress  + "%' \
        AND nics.removed is null;")
        result = cursor.fetchall()
        cursor.close()

        return result

    # list mac adress info
    def getMacAddressData(self, macaddress):
        if not self.conn:
            return 1

        cursor = self.conn.cursor()
        cursor.execute("SELECT networks.name, \
        nics.mac_address, \
        nics.ip4_address, \
        nics.netmask, \
        nics.broadcast_uri, \
        nics.mode, \
        nics.state, \
        nics.created, \
        vm_instance.name \
        FROM cloud.nics, cloud.vm_instance, \
        cloud.networks \
        WHERE nics.instance_id = vm_instance.id \
        AND nics.network_id = networks.id \
        AND mac_address \
        LIKE '%" + macaddress  + "%' \
        AND nics.removed is null;")
        result = cursor.fetchall()
        cursor.close()

        return result

    # Return uuid of router volume
    def getRouterRootVolumeUUID(self, routeruuid):
        if not self.conn:
            return 1
        if not routeruuid:
            return 1

        cursor = self.conn.cursor()
        cursor.execute("SELECT volumes.uuid, \
        volumes.name, \
        vm_instance.name \
        FROM volumes, vm_instance \
        WHERE volumes.instance_id = vm_instance.id \
        AND volumes.name like 'ROOT%' \
        AND volumes.state='Ready' \
        AND vm_instance.uuid = '" + routeruuid + "';")
        result = cursor.fetchall()
        cursor.close()

        return result

    # Return volumes that belong to a given instance ID
    def get_volumes_for_instance(self, instancename):
        if not self.conn:
            return 1
        if not instancename:
            return 1

        cursor = self.conn.cursor()
        cursor.execute("SELECT volumes.name, volumes.path FROM vm_instance, volumes"
                       " WHERE volumes.instance_id = vm_instance.id"
                       " AND instance_name='" + instancename + "';")
        result = cursor.fetchall()
        cursor.close()

        return result

    # Return new template id
    def get_template_id_from_name(self, template_name):
        if not self.conn:
            return False
        if not template_name:
            return False

        cursor = self.conn.cursor()
        cursor.execute("SELECT id FROM vm_template WHERE name = '" + template_name + "' AND removed is NULL LIMIT 1;")
        result = cursor.fetchall()
        cursor.close()

        return result

    # Return guest_os id
    def get_guest_os_id_from_name(self, guest_os_name):
        if not self.conn:
            return False
        if not guest_os_name:
            return False

        cursor = self.conn.cursor()
        cursor.execute("SELECT id from guest_os WHERE display_name ='"
                       + guest_os_name + "' AND removed is NULL LIMIT 1;")
        result = cursor.fetchall()
        cursor.close()

        return result

    # Return storage_pool id
    def get_storage_pool_id_from_name(self, storage_pool_name):
        if not self.conn:
            return False
        if not storage_pool_name:
            return False

        cursor = self.conn.cursor()
        cursor.execute("SELECT storage_pool.id FROM cluster, storage_pool WHERE storage_pool.cluster_id = cluster.id "
                       "AND cluster.name='" + storage_pool_name + "' AND removed is NULL LIMIT 1;")
        result = cursor.fetchall()
        cursor.close()

        return result

    # Return instance_id
    def get_istance_id_from_name(self, instance_name):
        if not self.conn:
            return False
        if not instance_name:
            return False

        cursor = self.conn.cursor()
        cursor.execute("SELECT id from vm_instance WHERE instance_name ='"
                       + instance_name + "' AND removed is NULL LIMIT 1;")
        result = cursor.fetchall()
        cursor.close()

        return result

    # Set instance to KVM in the db
    def update_instance_to_kvm(self, instance_name, vm_template_name, to_storage_pool_name,
                               guest_os_name="Other PV (64-bit)"):
        if not self.update_instance_from_xenserver_cluster_to_kvm_cluster(instance_name, vm_template_name,
                                                                          guest_os_name):
            print "Error: vm_instance query failed"
            return False
        if not self.update_all_volumes_of_instance_from_xenserver_cluster_to_kvm_cluster(instance_name,
                                                                                         to_storage_pool_name):
            print "Error: volumes query failed"
            return False
        return True

    # Update db vm_instance table
    def update_instance_from_xenserver_cluster_to_kvm_cluster(self, instance_name, vm_template_name, guest_os_name):
        if not self.conn:
            return False
        if not vm_template_name or not guest_os_name or not instance_name:
            return False

        vm_template_id = self.get_template_id_from_name(vm_template_name)
        guest_os_id = self.get_guest_os_id_from_name(guest_os_name)

        cursor = self.conn.cursor()

        try:
            cursor.execute ("""
               UPDATE vm_instance
               SET last_host_id=NULL, hypervisor_type='KVM', vm_template_id=%d, guest_os_id=%d
               WHERE instance_name=%s LIMIT 1
            """, (vm_template_id, guest_os_id, instance_name))

            cursor.commit()
        except MySQLdb.Error as e:
            print "Query failed"
            print e
            return False

        cursor.close()
        return True

    # Update db volumes table
    def update_all_volumes_of_instance_from_xenserver_cluster_to_kvm_cluster(self, instance_name, to_storage_pool_name):
        if not self.conn:
            return 1
        if not instance_name or not to_storage_pool_name:
            return 1

        instance_id = self.get_istance_id_from_name(instance_name)
        to_storage_pool_id = self.get_storage_pool_id_from_name(to_storage_pool_name)

        cursor = self.conn.cursor()

        try:
            cursor.execute ("""
               UPDATE volumes
               SET template_id=NULL, last_pool_id=NULL, format='QCOW2', pool_id=%d
               WHERE instance_id=%d LIMIT 1
            """, (to_storage_pool_id, instance_id))

            cursor.commit()
        except MySQLdb.Error as e:
            print "Query failed"
            print e
            return False

        cursor.close()
        return True
