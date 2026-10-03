#include <libproc.h>
#include <sys/resource.h>
#include <stdio.h>
#include <stdlib.h>
int main(int argc, char **argv) {
  for (int i=1; i<argc; i++) {
    struct rusage_info_v4 r;
    int pid=atoi(argv[i]);
    if (proc_pid_rusage(pid,RUSAGE_INFO_V4,(rusage_info_t*)&r)==0)
      printf("%d %llu %llu\n",pid,r.ri_phys_footprint,r.ri_resident_size);
  }
  return 0;
}
