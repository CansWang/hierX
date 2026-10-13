/* A wrapper over a variant target (`dup_t`) that also points at the opaque handle: adding the UNRELATED complete
   `struct handle` of src/impl.c to the build must not change its variant ids (review round 9). */
#ifndef HBOX_H
#define HBOX_H

#include "common.h"
#include "handle.h"

struct hbox { dup_t *payload; struct handle *h; };

#endif
