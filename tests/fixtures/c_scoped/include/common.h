/* One forward declaration and one typedef shared by two TUs that define `struct dup` DIFFERENTLY, plus a
   wrapper whose listed fields are identical everywhere but whose `payload` resolves to different layouts. */
#ifndef COMMON_H
#define COMMON_H

struct dup;
typedef struct dup dup_t;

struct box { dup_t *payload; };

#endif
