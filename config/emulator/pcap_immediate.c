/*
 * pcap_immediate.c - LD_PRELOAD shim to fix pcap receive on Linux
 *
 * Problem: xemu calls pcap_open_live() which does NOT enable immediate mode.
 * On Linux with libpcap >= 1.9 and TPACKET_V3, this causes
 * pcap_get_selectable_fd() to return an fd that never becomes readable,
 * so xemu's event loop never processes incoming packets.
 *
 * Fix: Intercept pcap_open_live() and replace it with the equivalent
 * pcap_create/pcap_set_immediate_mode/pcap_activate sequence.
 * We use RTLD_NEXT to call the real functions from whatever libpcap is
 * loaded (including xemu's bundled version).
 *
 * Build:
 *   gcc -shared -fPIC -o pcap_immediate.so pcap_immediate.c -ldl
 *
 * Usage:
 *   Add to /etc/ld.so.preload (required for setcap binaries).
 */

#define _GNU_SOURCE
#include <dlfcn.h>
#include <stdio.h>
#include <pcap/pcap.h>

pcap_t *pcap_open_live(const char *device, int snaplen, int promisc,
                       int to_ms, char *errbuf)
{
    static pcap_t *(*real_pcap_create)(const char *, char *) = NULL;
    static int (*real_pcap_set_snaplen)(pcap_t *, int) = NULL;
    static int (*real_pcap_set_promisc)(pcap_t *, int) = NULL;
    static int (*real_pcap_set_timeout)(pcap_t *, int) = NULL;
    static int (*real_pcap_set_immediate_mode)(pcap_t *, int) = NULL;
    static int (*real_pcap_activate)(pcap_t *) = NULL;
    static const char *(*real_pcap_statustostr)(int) = NULL;
    static const char *(*real_pcap_geterr)(pcap_t *) = NULL;
    static void (*real_pcap_close)(pcap_t *) = NULL;

    if (!real_pcap_create) {
        real_pcap_create = dlsym(RTLD_NEXT, "pcap_create");
        real_pcap_set_snaplen = dlsym(RTLD_NEXT, "pcap_set_snaplen");
        real_pcap_set_promisc = dlsym(RTLD_NEXT, "pcap_set_promisc");
        real_pcap_set_timeout = dlsym(RTLD_NEXT, "pcap_set_timeout");
        real_pcap_set_immediate_mode = dlsym(RTLD_NEXT, "pcap_set_immediate_mode");
        real_pcap_activate = dlsym(RTLD_NEXT, "pcap_activate");
        real_pcap_statustostr = dlsym(RTLD_NEXT, "pcap_statustostr");
        real_pcap_geterr = dlsym(RTLD_NEXT, "pcap_geterr");
        real_pcap_close = dlsym(RTLD_NEXT, "pcap_close");
    }

    pcap_t *p = real_pcap_create(device, errbuf);
    if (!p) return NULL;

    real_pcap_set_snaplen(p, snaplen);
    real_pcap_set_promisc(p, promisc);
    real_pcap_set_timeout(p, to_ms);
    real_pcap_set_immediate_mode(p, 1);

    int status = real_pcap_activate(p);
    if (status < 0) {
        if (errbuf) {
            snprintf(errbuf, PCAP_ERRBUF_SIZE, "%s: %s",
                     device, real_pcap_statustostr(status));
        }
        real_pcap_close(p);
        return NULL;
    } else if (status > 0 && errbuf) {
        snprintf(errbuf, PCAP_ERRBUF_SIZE, "%s: %s (%s)",
                 device, real_pcap_statustostr(status), real_pcap_geterr(p));
    }

    return p;
}
