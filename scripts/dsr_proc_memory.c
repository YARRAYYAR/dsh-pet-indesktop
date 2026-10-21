#include <libproc.h>
#include <sys/resource.h>
#include <stdio.h>
#include <stdlib.h>
/* The first three columns retain the existing memory-probe interface.
 * CPU times are raw Mach absolute-time ticks; the Python consumer converts
 * them using mach_timebase_info. Wakeups are cumulative kernel counters.
 * XNU: osfmk/kern/task.c task_power_info_locked -> rm_time_mach. */
int main(int argc, char **argv) {
  for (int i = 1; i < argc; i++) {
    struct rusage_info_v4 r;
    int pid = atoi(argv[i]);
    if (proc_pid_rusage(pid, RUSAGE_INFO_V4, (rusage_info_t *)&r) == 0)
      printf("%d %llu %llu %llu %llu %llu %llu %llu %llu %llu %llu\n",
             pid, r.ri_phys_footprint, r.ri_resident_size,
             r.ri_user_time, r.ri_system_time,
             r.ri_pkg_idle_wkups, r.ri_interrupt_wkups,
             r.ri_child_user_time, r.ri_child_system_time,
             r.ri_child_pkg_idle_wkups, r.ri_child_interrupt_wkups);
  }
  return 0;
}
