<%
    cfg = dispatcher.call_sync('service.glusterd.get_config')
%>\
/var/log/glusterfs/geo-replication/*/*.log {
    sharedscripts
    rotate 52
    missingok
    compress
    delaycompress
    notifempty
    postrotate
    for pid in `ps -aef | grep glusterfs | egrep "\-\-aux-gfid-mount" | awk '{print $2}'`; do
        /usr/bin/kill -HUP $pid > /dev/null 2>&1 || true
    done
     endscript
}


/var/log/glusterfs/geo-replication-slaves/*.log {
    sharedscripts
    rotate 52
    missingok
    compress
    delaycompress
    notifempty
    postrotate
    for pid in `ps -aef | grep glusterfs | egrep "\-\-aux-gfid-mount" | awk '{print $2}'`; do
        /usr/bin/kill -HUP $pid > /dev/null 2>&1 || true
    done
    endscript
}


/var/log/glusterfs/geo-replication-slaves/*/*.log {
    sharedscripts
    rotate 52
    missingok
    compress
    delaycompress
    notifempty
    postrotate
    for pid in `ps -aef | grep glusterfs | egrep "\-\-aux-gfid-mount" | awk '{print $2}'`; do
        /usr/bin/kill -HUP $pid > /dev/null 2>&1 || true
    done
    endscript
}
