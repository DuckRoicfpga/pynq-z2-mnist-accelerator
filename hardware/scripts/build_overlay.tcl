set script_dir [file dirname [file normalize [info script]]]
set root_dir [file dirname [file dirname $script_dir]]
set hw_dir [file join $root_dir hardware]
set out_dir [file join $root_dir output stage3]
file mkdir $out_dir
set_param general.maxThreads 6
source [file join $script_dir package_ip.tcl]
set boards [get_board_parts -quiet *pynq-z2*]
if {[llength $boards] == 0} {
    set_param board.repoPaths [list [file join $hw_dir board_files]]
    set boards [get_board_parts -quiet *pynq-z2*]
}
if {[llength $boards] == 0} { error "PYNQ-Z2 board files not found" }
set board [lindex $boards 0]
create_project -force mnist_pynq_z2 [file join $hw_dir build mnist_pynq_z2] -part xc7z020clg400-1
set_property board_part $board [current_project]
set_property target_language Verilog [current_project]
set_property ip_repo_paths [list [file join $hw_dir ip_repo]] [current_project]
update_ip_catalog
create_bd_design mnist_system
set ps [create_bd_cell -type ip -vlnv xilinx.com:ip:processing_system7:5.5 processing_system7_0]
apply_bd_automation -rule xilinx.com:bd_rule:processing_system7 -config {make_external "FIXED_IO, DDR" apply_board_preset "1" Master "Disable" Slave "Disable"} $ps
set_property -dict [list CONFIG.PCW_USE_M_AXI_GP0 {1} CONFIG.PCW_EN_CLK0_PORT {1} CONFIG.PCW_EN_RST0_PORT {1} CONFIG.PCW_FPGA0_PERIPHERAL_FREQMHZ {100} CONFIG.PCW_USE_FABRIC_INTERRUPT {1} CONFIG.PCW_IRQ_F2P_INTR {1}] $ps
# The vendor preset gives this derived value USER strength; allow clock
# propagation from the actual 100 MHz GP0 clock instead of forcing it manually.
set_property CONFIG.PCW_M_AXI_GP0_FREQMHZ.VALUE_SRC DEFAULT $ps
set ai [create_bd_cell -type ip -vlnv mnist.local:user:mlp_axi_lite:1.0 mlp_ai_0]
set_property CONFIG.CLOCK_HZ 100000000 $ai
set interconnect [create_bd_cell -type ip -vlnv xilinx.com:ip:axi_interconnect:2.1 axi_interconnect_0]
set_property CONFIG.NUM_MI 1 $interconnect
set reset [create_bd_cell -type ip -vlnv xilinx.com:ip:proc_sys_reset:5.0 rst_fclk0]
set one [create_bd_cell -type ip -vlnv xilinx.com:ip:xlconstant:1.1 const_one]
set_property -dict [list CONFIG.CONST_WIDTH 1 CONFIG.CONST_VAL 1] $one
set zero [create_bd_cell -type ip -vlnv xilinx.com:ip:xlconstant:1.1 const_zero]
set_property -dict [list CONFIG.CONST_WIDTH 1 CONFIG.CONST_VAL 0] $zero
set concat [create_bd_cell -type ip -vlnv xilinx.com:ip:xlconcat:2.1 irq_concat]
set_property CONFIG.NUM_PORTS 1 $concat
connect_bd_intf_net [get_bd_intf_pins processing_system7_0/M_AXI_GP0] [get_bd_intf_pins axi_interconnect_0/S00_AXI]
connect_bd_intf_net [get_bd_intf_pins axi_interconnect_0/M00_AXI] [get_bd_intf_pins mlp_ai_0/S_AXI]
connect_bd_net [get_bd_pins processing_system7_0/FCLK_CLK0] [get_bd_pins processing_system7_0/M_AXI_GP0_ACLK] [get_bd_pins axi_interconnect_0/ACLK] [get_bd_pins axi_interconnect_0/S00_ACLK] [get_bd_pins axi_interconnect_0/M00_ACLK] [get_bd_pins rst_fclk0/slowest_sync_clk] [get_bd_pins mlp_ai_0/s_axi_aclk]
connect_bd_net [get_bd_pins processing_system7_0/FCLK_RESET0_N] [get_bd_pins rst_fclk0/ext_reset_in]
connect_bd_net [get_bd_pins const_one/dout] [get_bd_pins rst_fclk0/dcm_locked] [get_bd_pins rst_fclk0/aux_reset_in]
connect_bd_net [get_bd_pins const_zero/dout] [get_bd_pins rst_fclk0/mb_debug_sys_rst]
connect_bd_net [get_bd_pins rst_fclk0/interconnect_aresetn] [get_bd_pins axi_interconnect_0/ARESETN]
connect_bd_net [get_bd_pins rst_fclk0/peripheral_aresetn] [get_bd_pins axi_interconnect_0/S00_ARESETN] [get_bd_pins axi_interconnect_0/M00_ARESETN] [get_bd_pins mlp_ai_0/s_axi_aresetn]
connect_bd_net [get_bd_pins mlp_ai_0/irq] [get_bd_pins irq_concat/In0]
connect_bd_net [get_bd_pins irq_concat/dout] [get_bd_pins processing_system7_0/IRQ_F2P]
assign_bd_address -offset 0x40000000 -range 0x00010000 -target_address_space [get_bd_addr_spaces processing_system7_0/Data] [get_bd_addr_segs mlp_ai_0/S_AXI/Reg] -force
validate_bd_design
save_bd_design
write_bd_tcl -force [file join $out_dir mnist_system.tcl]
set bd_file [get_files */mnist_system.bd]
generate_target all $bd_file
set wrapper [make_wrapper -files $bd_file -top]
add_files -norecurse [list $wrapper]
set_property top mnist_system_wrapper [current_fileset]
update_compile_order -fileset sources_1
launch_runs synth_1 -jobs 6
wait_on_run synth_1
if {[get_property PROGRESS [get_runs synth_1]] != "100%"} { error "Synthesis failed" }
launch_runs impl_1 -to_step write_bitstream -jobs 6
wait_on_run impl_1
if {[get_property PROGRESS [get_runs impl_1]] != "100%"} { error "Implementation/bitstream failed" }
open_run impl_1
report_timing_summary -delay_type min_max -report_unconstrained -check_timing_verbose -file [file join $out_dir timing_post_route.rpt]
report_utilization -hierarchical -file [file join $out_dir utilization_post_route.rpt]
report_drc -file [file join $out_dir drc_post_route.rpt]
set setup_path [get_timing_paths -delay_type max -max_paths 1]
set hold_path [get_timing_paths -delay_type min -max_paths 1]
set setup_slack [get_property SLACK $setup_path]
set hold_slack [get_property SLACK $hold_path]
set critical_drc [get_drc_violations -quiet -filter {SEVERITY == Error || SEVERITY == {Critical Warning}}]
if {$setup_slack < 0 || $hold_slack < 0} { error "Timing failed: setup=$setup_slack hold=$hold_slack" }
if {[llength $critical_drc] != 0} { error "Critical DRC violations remain: $critical_drc" }
set run_dir [get_property DIRECTORY [get_runs impl_1]]
file copy -force [file join $run_dir mnist_system_wrapper.bit] [file join $out_dir mnist_mlp.bit]
set hwh_files [glob -nocomplain [file join $hw_dir build mnist_pynq_z2 mnist_pynq_z2.gen sources_1 bd mnist_system hw_handoff *.hwh]]
if {[llength $hwh_files] != 1} { error "Expected one HWH handoff file, found: $hwh_files" }
file copy -force [lindex $hwh_files 0] [file join $out_dir mnist_mlp.hwh]
write_hw_platform -fixed -include_bit -force -file [file join $out_dir mnist_mlp.xsa]
set fp [open [file join $out_dir implementation_status.txt] w]
puts $fp "BOARD=$board"
puts $fp "CLOCK_HZ=100000000"
puts $fp "AXI_BASE=0x40000000"
puts $fp "AXI_RANGE=0x00010000"
puts $fp "SETUP_SLACK_NS=$setup_slack"
puts $fp "HOLD_SLACK_NS=$hold_slack"
puts $fp "CRITICAL_DRC_COUNT=[llength $critical_drc]"
close $fp
puts "STAGE3_BUILD_COMPLETE: setup=$setup_slack hold=$hold_slack"
exit
