/* Function-local types (review round 9): two functions each define a `struct local` with a different layout, and
   one function defines `struct blk` twice in two blocks. Each type is reached through a function-static instance
   (nothing else records a local type) and each function returns the size of its own type, so the compiler oracle
   can CALL it: `sizeof` in a generated `main` cannot see a function-local type. */
int loc_f(void) { struct local { int a; }; static struct local v; return v.a + (int)sizeof v; }

int loc_g(void) { struct local { int a; int b; int c; int d; }; static struct local v; return v.a + (int)sizeof v; }

int loc_h(void)
{
    int s = 0;
    { struct blk { char c; }; static struct blk b1; s += b1.c + (int)sizeof b1; }
    { struct blk { long l; }; static struct blk b2; s += (int)b2.l + (int)sizeof b2; }
    return s;
}
