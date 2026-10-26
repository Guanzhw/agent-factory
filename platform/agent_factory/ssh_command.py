"""Fixed OpenSSH policy; credentials and process ownership stay with each platform."""


def pinned_arguments(executable, server, command, credential_args, *, forward=None):
    args = [str(executable), '-F', 'none', '-a', '-T', '-o', 'HostKeyAlias=factory-pinned',
        '-o', 'StrictHostKeyChecking=yes', '-o', 'UserKnownHostsFile=known_hosts',
        '-o', 'GlobalKnownHostsFile=none', '-o', 'IdentitiesOnly=yes',
        '-o', 'PasswordAuthentication=no', '-o', 'KbdInteractiveAuthentication=no',
        '-o', 'ProxyCommand=none', '-o', 'ProxyJump=none', '-o', 'ControlMaster=no', '-o', 'ControlPath=none',
        '-o', 'PermitLocalCommand=no', '-o', 'ExitOnForwardFailure=yes', '-o', 'StreamLocalBindUnlink=no',
        '-o', 'ConnectTimeout=10', '-o', 'ServerAliveInterval=10', '-o', 'ServerAliveCountMax=2']
    args += credential_args
    if forward:
        args += ['-R', forward]
    return args + ['-l', server.username, '-p', str(server.port), server.address, command]
