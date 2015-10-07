<%
    cfg = dispatcher.call_sync('service.swift_swift_rsyslog.get_config')
%>\
# Uncomment the following to have a log containing all logs together
#local.* /var/log/swift/all.log

# Uncomment the following to have hourly swift logs.
#$template HourlyProxyLog,"/var/log/swift/hourly/%$YEAR%%$MONTH%%$DAY%%$HOUR%"
#local0.* ?HourlyProxyLog

# Use the following to have separate log files for each of the main servers:
# account-server, container-server, object-server, proxy-server. Note:
# object-updater's output will be stored in object.log.
if $programname contains 'swift' then /var/log/swift/swift.log
if $programname contains 'account' then /var/log/swift/account.log
if $programname contains 'container' then /var/log/swift/container.log
if $programname contains 'object' then /var/log/swift/object.log
if $programname contains 'proxy' then /var/log/swift/proxy.log

# Uncomment the following to have specific log via program name.
#if $programname == 'swift' then /var/log/swift/swift.log
#if $programname == 'account-server' then /var/log/swift/account-server.log
#if $programname == 'account-replicator' then /var/log/swift/account-replicator.log
#if $programname == 'account-auditor' then /var/log/swift/account-auditor.log
#if $programname == 'account-reaper' then /var/log/swift/account-reaper.log
#if $programname == 'container-server' then /var/log/swift/container-server.log
#if $programname == 'container-replicator' then /var/log/swift/container-replicator.log
#if $programname == 'container-updater' then /var/log/swift/container-updater.log
#if $programname == 'container-auditor' then /var/log/swift/container-auditor.log
#if $programname == 'container-sync' then /var/log/swift/container-sync.log
#if $programname == 'object-server' then /var/log/swift/object-server.log
#if $programname == 'object-replicator' then /var/log/swift/object-replicator.log
#if $programname == 'object-updater' then /var/log/swift/object-updater.log
#if $programname == 'object-auditor' then /var/log/swift/object-auditor.log

# Use the following to discard logs that don't match any of the above to avoid
# them filling up /var/log/messages.
local0.* ~