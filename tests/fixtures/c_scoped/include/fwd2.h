/* A SECOND forward declaration of `struct fwd`. src/t4.c includes complete.h first, so this declaration is never a
   TU's first one: only a chain that records every declaration file links it to the definition (review round 9). */
#ifndef FWD2_H
#define FWD2_H

struct fwd;
int t5(struct fwd *p);

#endif
