<%
    adv_config = dispatcher.call_sync('system.advanced.get_config')
    gen_config = dispatcher.call_sync('system.general.get_config')
%>\
hostname="${gen_config["hostname"]}"
local_startup="/usr/local/etc/rc.d"
early_late_divider="*"
root_rw_mount="YES"
clear_tmpX="NO"
background_fsck="NO"
fsck_y_enable="YES"
synchronous_dhclient="YES"

# middleware10
dispatcher_enable="YES"
dispatcher_flags="--log-level=DEBUG"
datastore_enable="YES"
datastore_dbdir="/data"
datastore_driver="mongodb"
etcd_enable="YES"
etcd_flags="-c /usr/local/etc/middleware.conf /etc"
networkd_enable="YES"
schedulerd_enable="YES"
syslogd_enable="NO"
syslog_ng_enable="YES"
# turbo boost
performance_cpu_freq="HIGH"

devfs_system_ruleset="usbrules"

# open-vm-tools
vmware_guest_vmblock_enable="YES"
vmware_guest_vmhgfs_enable="YES"
vmware_guest_vmmemctl_enable="YES"
vmware_guest_vmxnet_enable="YES"
vmware_guestd_enable="YES"

# Do not mark to autodetach otherwise ZFS get very unhappy
geli_autodetach="NO"

# A set of storage supporting kernel modules, they must be loaded before ix-fstab.
early_kld_list="geom_stripe geom_raid3 geom_raid5 geom_gate geom_multipath"

# A set of kernel modules that can be loaded after mounting local filesystems.
kld_list="dtraceall ipmi if_cxgbe"

dbus_enable="YES"
mdnsd_enable="YES"
nginx_enable="YES"

# START - FreeNAS 9.x, remove when rc.conf.local migration completed
# Add our rc.d scripts to load path
local_startup="/etc/ix.rc.d /usr/local/etc/rc.d"
# Make sure ix scripts run early enough
early_late_divider="*"
# END

# AppCafe related services
syscache_enable="YES"
appcafe_enable="YES"

collectd_enable="YES"
ntpd_enable="YES"
ntpd_sync_on_start="YES"

# Selectively enable services for now
% for svc in ds.query("service_definitions", ('name', 'in', ['afp', 'ftp', 'ipfs'])):
    % if config.get("service.{0}.enable".format(svc["name"])):
${svc['rcng']['rc-scripts']}_enable="YES"
    % endif
% endfor
% if config.get("service.cifs.enable"):
samba_server_enable="YES"
##% if ! dirsrv_enabled domaincontroller
smbd_enable="YES"
nmbd_enable="YES"
winbindd_enable="YES"
##% endif
% endif
% if config.get("service.dyndns.enable"):
inadynmt_enable="YES"
% endif

% if gen_config['console_keymap']:
keymap="${gen_config['console_keymap']}"
% endif

% for ctl in dispatcher.call_sync('tunables.query', [('type', '=', 'RC')]):
% if ctl.get('enabled', True):
${ctl['var']}="${ctl['value']}"
% endif
% endfor

% if adv_config.get('console_screensaver'):
saver="daemon"
% endif

# Get crashdumps
dumpdev="AUTO"
dumpdir="/data/crash"
savecore_flags="-z -m 5"
% if adv_config.get('uploadcrash'):
ix_diagnose_enable="YES"
% endif

% if adv_config.get('powerd'):
powerd_enable="YES"
% endif
