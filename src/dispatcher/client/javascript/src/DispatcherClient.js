/*
 * Copyright 2015 iXsystems, Inc.
 * All rights reserved
 *
 * Redistribution and use in source and binary forms, with or without
 * modification, are permitted providing that the following conditions
 * are met:
 * 1. Redistributions of source code must retain the above copyright
 *    notice, this list of conditions and the following disclaimer.
 * 2. Redistributions in binary form must reproduce the above copyright
 *    notice, this list of conditions and the following disclaimer in the
 *    documentation and/or other materials provided with the distribution.
 *
 * THIS SOFTWARE IS PROVIDED BY THE AUTHOR ``AS IS'' AND ANY EXPRESS OR
 * IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE IMPLIED
 * WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE
 * ARE DISCLAIMED.  IN NO EVENT SHALL THE AUTHOR BE LIABLE FOR ANY
 * DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL
 * DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS
 * OR SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION)
 * HOWEVER CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT,
 * STRICT LIABILITY, OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING
 * IN ANY WAY OUT OF THE USE OF THIS SOFTWARE, EVEN IF ADVISED OF THE
 * POSSIBILITY OF SUCH DAMAGE.
 *
 */

const INVALID_JSON_RESPONSE = 1;
const CONNECTION_TIMEOUT = 2;
const CONNECTION_CLOSED = 3;
const RPC_CALL_TIMEOUT = 4;
const RPC_CALL_ERROR = 5;
const SPURIOUS_RPC_RESPONSE = 6;
const LOGOUT = 7;
const OTHER = 8;

import { getErrno, getCode } from './ErrnoCodes.js'
export { getErrno, getCode }
export { ShellClient } from './ShellClient'
export { EntitySubscriber } from './EntitySubscriber.js'

export class RPCException
{
    constructor(code, message, extra=null, stacktrace=null)
    {
        this.code = code;
        this.message = message;
        this.extra = extra;
        this.stacktrace = stacktrace;
    }
}

export class DispatcherClient
{
    constructor(hostname)
    {
        this.defaultTimeout = 20;
        this.hostname = hostname;
        this.socket = null;
        this.pendingCalls = new Map();
        this.eventHandlers = new Map();
        this.subscriptions = new Map();

        /* Callbacks */
        this.onEvent = () => {};
        this.onConnect = () => {};
        this.onDisconnect = () => {};
        this.onLogin = () => {};
        this.onRPCResponse = () => {};
        this.onError = () => {};
    }

    __onmessage(msg)
    {
        try {
            var data = JSON.parse(msg.data);
        } catch (e) {
            console.warn(`Malformed response: "${msg.data}"`);
            this.onError(INVALID_JSON_RESPONSE);
            return;
        }

        if (data.namespace == "events" && data.name == "event") {
            if (this.eventHandlers.has(data.args.name)) {
                for (let e of this.eventHandlers.values()) {
                    e(data.args.args);
                }
            }

            this.onEvent(data.args.name, data.args.args);
            return;
        }

        if (data.namespace == "events" && data.name == "logout") {
            this.onError(LOGOUT);
            return;
        }

        if (data.namespace == "rpc") {
            if (data.name == "call") {
                console.error("Server functionality is not supported");
                this.onError(SPURIOUS_RPC_RESPONSE);
                return;
            }

            if (data.name == "response" || data.name == "error") {
                if (!this.pendingCalls.has(data.id)) {
                    console.warn(`Spurious RPC response: ${data.id}`);
                    this.onError(SPURIOUS_RPC_RESPONSE);
                    return;
                }

                var result = data.args;
                if (data.name == "error") {
                    result = new RPCException(
                        data.args.code,
                        data.args.message,
                        data.args.extra,
                        data.args.stacktrace
                    );
                }

                let call = this.pendingCalls.get(data.id);
                clearTimeout(call.timeout);
                call.callback(result);
                this.pendingCalls.delete(data.id);
            }
        }
    }

    __onopen()
    {
        console.log("Connection established");
        this.onConnect();
    }

    __onclose()
    {
        let errno = getCode("ECONNRESET");

        for (let call of this.pendingCalls.values()) {
            call.callback(new RPCException(
                errno.code,
                errno.description
            ));
        }

        console.log("Connection closed");
        this.onDisconnect();
    }

    __ontimeout(id)
    {
        let call = this.pendingCalls.get(id);
        let errno = getCode("ETIMEDOUT");

        call.callback(new RPCException(
            errno.code,
            errno.description
        ));

        this.pendingCalls.delete(id);
        this.onError(RPC_CALL_TIMEOUT, call.method, call.args);
    }

    static __uuid() {
        return "xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx".replace( /[xy]/g, c => {
            var r = Math.random() * 16 | 0, v = c == "x" ? r : (r & 0x3 | 0x8);
            return v.toString(16);
        });
    }

    static __pack(namespace, name, args, id)
    {
        return JSON.stringify({
            "namespace": namespace,
            "id": id || DispatcherClient.__uuid(),
            "name": name,
            "args": args
        });
    }

    connect()
    {
        this.socket = new WebSocket(`ws://${this.hostname}:5000/socket`);
        this.socket.onmessage = this.__onmessage.bind(this);
        this.socket.onopen = this.__onopen.bind(this);
        this.socket.onclose = this.__onclose.bind(this);
    }

    disconnect()
    {
        this.socket.close();
    }

    login(username, password)
    {
        let id = DispatcherClient.__uuid();
        let payload = {
            "username": username,
            "password": password
        };

        this.pendingCalls.set(id, {
            "callback": () => this.onLogin()
        });

        this.socket.send(DispatcherClient.__pack("rpc", "auth", payload, id));
    }

    call(method, args, callback)
    {
        let id = DispatcherClient.__uuid();
        let timeout = setTimeout(() => { this.__ontimeout(id); }, this.defaultTimeout * 1000);
        let payload = {
            "method": method,
            "args": args
        };

        this.pendingCalls.set(id, {
            "method": method,
            "args": args,
            "callback": callback,
            "timeout": timeout
        });

        this.socket.send(DispatcherClient.__pack("rpc", "call", payload, id));
    }

    subscribe(pattern)
    {
        if (!this.subscriptions.has(pattern)) {
            this.socket.send(DispatcherClient.__pack("events", "subscribe", [pattern]));
            this.subscriptions.set(pattern, 0);
        }

        let refcount = this.subscriptions.get(pattern) + 1;
        this.subscriptions.set(pattern, refcount);
    }

    unsubscribe(pattern)
    {
        if (!this.subscriptions.has(pattern)) {
            throw new Error(`No previous subscription for ${pattern}`)
        }

        let refcount = this.subscriptions.get(pattern) - 1;
        this.subscriptions.set(pattern, refcount);

        if (refcount === 0) {
            this.socket.send(DispatcherClient.__pack("events", "unsubscribe", [pattern]));
            this.subscriptions.delete(pattern);
        }
    }

    emitEvent(name, args)
    {
        this.socket.send(DispatcherClient.__pack("events", "event", {
            "name": name,
            "args": "args"
        }));
    }

    registerEventHandler(name, callback)
    {
        if (!this.eventHandlers.has(name)) {
            this.eventHandlers.set(name, new Map());
        }

        let cookie = DispatcherClient.__uuid();
        let list = this.eventHandlers.get(name);
        list.set(cookie, callback);
        this.subscribe(name);
    }

    unregisterEventHandler(name, cookie)
    {
        if (!this.eventHandlers.has(name)) {
            throw new Error(`there are no handlers registered for ${name}`);
        }

        let list = this.eventHandlers.get(name);
        if (!list.has(cookie)) {
            throw new Error("no handler registered for that cookie");
        }

        this.unsubscribe(name);
        list.delete(cookie);
    }
}
