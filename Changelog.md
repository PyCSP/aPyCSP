2018-04-05 14:08
     Added alternative/initial exerimental implementation where we remove locks and 
     condition variables and simplify the channel implementation using 
     opcode queues. An initial experimental comparison using a producer/consumer 
     setup over a channel results in the following times per message on daohost01:
     
     channel_simple_read_write.py
     base impl         :  ~ 22.7us/msg
     base impl uvloop  :  ~ 14.1us/msg
     alt impl          :  ~  6.9us/msg
     alt impl uvloop   :  ~  3.5us/msg
     
     Testing with n_procs, we get the following RSS reported at max: 
     with uvloop: 
     base: (5276930048-20844544) / (1_000_000 - 10.0) = 5256.138065380654
     alt : (4183818240-20652032) / (1_000_000 - 10.0) = 4163.207840078401

     Without uvloop: 
     base: (5133414400-19542016) / (1_000_000 - 10.0) = 5113.923523235232
     alt:  (4101144576-19533824) / (1_000_000 - 10.0) = 4081.651568515685
     
     So uvloop actually adds a slight overhead per process! 
     Also, there is a significant advantage (20% or about 1KB) to using the altimpl
     when it comes to memory usage. 
     
     ALT is not implemented yet, and will probably add a little overhead. 
     There is also no poison implementation. 
     
     The ChannelEnds also add a slight overhead that we could 
     consider removing later. 


 
