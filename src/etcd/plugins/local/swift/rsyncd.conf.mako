<%
    cfg = dispatcher.call_sync('service.swift_rsync.get_config')
%>\
uid = swift
gid = swift
log file = /var/log/rsyncd.log
pid file = /var/run/rsyncd.pid

[account]
max connections = 2
path = /srv/node
read only = false
lock file = /var/lock/account.lock

[container]
max connections = 4
path = /srv/node
read only = false
lock file = /var/lock/container.lock

[object]
max connections = 8
path = /srv/node
read only = false
lock file = /var/lock/object.lock