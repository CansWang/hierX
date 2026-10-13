struct sb;
struct sa { struct sb *b; int av; };
struct sb { struct sa *a; int bv; };

int s2(struct sa *p) { return p->av; }
