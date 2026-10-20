# Standalone synthesis check for the existing accelerator, before AXI packaging.
set validation_dir [file dirname [file normalize [info script]]]
set root_dir [file dirname $validation_dir]
set synth_dir [file join $root_dir output validation synthesis]
file mkdir $synth_dir
create_project -in_memory -part xc7z020clg400-1
set_property target_language Verilog [current_project]
set_property include_dirs [list [file join $root_dir rtl]] [current_fileset]
read_verilog [list [file join $root_dir rtl mlp_accelerator.v]]
foreach name {fc1_weight.mem fc2_weight.mem fc3_weight.mem fc1_bias.mem fc2_bias.mem fc3_bias.mem} {
    add_files -norecurse [list [file join $root_dir output fpga_mem $name]]
}
synth_design -top mlp_accelerator -part xc7z020clg400-1
create_clock -period 10.000 -name accelerator_clk [get_ports clk]
report_utilization -file [file join $synth_dir utilization.rpt]
report_timing_summary -file [file join $synth_dir timing_summary.rpt]
report_drc -file [file join $synth_dir drc.rpt]
write_checkpoint -force [file join $synth_dir mlp_accelerator_synth.dcp]
puts "SYNTHESIS_CHECK_COMPLETE"
exit
