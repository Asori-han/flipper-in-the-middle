require "combine_pdf"

preface, body, output = ARGV
abort "usage: combine_pdf.rb PREFACE BODY OUTPUT" unless output
pdf = CombinePDF.new
pdf << CombinePDF.load(preface)
pdf << CombinePDF.load(body)
pdf.save output
