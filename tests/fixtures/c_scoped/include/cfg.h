/* One declaration file, two layouts: TUs compiled with and without -DWIDE see different structs and enums. */
#ifndef CFG_H
#define CFG_H

struct cfg {
    int a;
#ifdef WIDE
    long long b;
#endif
    int c;
};

enum mode {
    M_A,
    M_B
#ifdef WIDE
    , M_C
#endif
};

#endif
