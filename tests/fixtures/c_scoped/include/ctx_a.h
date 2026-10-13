/* A typedef REDECLARED in two headers (FFmpeg's `typedef struct AVFormatContext AVFormatContext;` in avformat.h and
   avio_internal.h): libclang's typedef USR carries whichever header a TU saw first, so the two spellings must be
   reconciled over chains like a tag's canonical declaration. Both name the one `struct rctx` defined here. */
#ifndef CTX_A_H
#define CTX_A_H

typedef struct rctx rctx_t;
struct rctx { int a; int b; };
struct holder { rctx_t *ctx; int n; };

#endif
