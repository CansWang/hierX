/* A private a/b pair with the same bodies as s2.c: distinct types because they are defined in different files. */
struct sb;
struct sa { struct sb *b; int av; };
struct sb { struct sa *a; int bv; };

int s1(struct sa *p) { return p->av; }
